"""Clinical trials of the watched ingredients, from ClinicalTrials.gov (migration 0067).

    python -m collectors.trials        every active ingredient (the weekly "PHAROS clinical trials" workflow)

For each active ingredient ClinicalTrials.gov (API v2, no key) is asked for the studies whose interventions name
it: its English name and its other English names in ``ingredient_term`` (codes left out), as one "OR" search,
1,000 studies a page. The list gives each study's last update; only a study that is new or was updated since it was
kept is fetched again, 100 at a time: title, phase, overall status, start and completion dates, lead sponsor,
enrolment, whether results are posted, and the adverse-event tables of its results (serious and other, each term
summed over the groups, with each group's numbers kept beside it). The terms are the sponsor's words as published,
usually MedDRA terms: they are kept and shown as they are and never made into a dictionary (PHAROS holds no MedDRA
licence). A status different from the one kept is dated (``trial.status_changed_on``). A study the search no longer
returns is unlinked, but only after a search that read every page. ``ingredient_trials()`` shows it all on the
Ingredients screen.

The run logs are public: they print counts only, never an ingredient, a sponsor or a request address.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any, Callable

log = logging.getLogger("collectors.trials")

API = "https://clinicaltrials.gov/api/v2/studies"
LIST_PAGE = 1000       # the API's largest page
FETCH_BATCH = 100      # studies fetched at once by id
GAP_S = 1.3            # ClinicalTrials.gov asks for about 50 requests a minute at most
MAX_NAMES = 10         # names in one search
MAX_PAGES = 200        # 200,000 studies: far beyond any one ingredient
LIST_FIELDS = "NCTId,LastUpdatePostDate"
STUDY_FIELDS = ",".join([
    "NCTId", "BriefTitle", "Phase", "OverallStatus", "StartDate", "CompletionDate", "LeadSponsorName",
    "EnrollmentCount", "EnrollmentType", "HasResults", "LastUpdatePostDate", "ResultsFirstPostDate",
    "AdverseEventsModule",
])

Get = Callable[[dict], dict]

INGREDIENTS_SQL = """
select i.id::text as id, i.inn_en,
       coalesce(array_agg(distinct t.term) filter (where t.term is not null), '{}') as terms
  from ingredient i
  left join ingredient_term t on t.ingredient_id = i.id and t.lang = 'en' and t.kind <> 'code'
 where i.active
 group by i.id, i.inn_en
 order by i.inn_en
"""

KNOWN_SQL = "select nct_id, last_update_on::text as last_update from trial where nct_id = any(%(ids)s)"

# A status different from the one kept is dated, in Cairo; the first time a study is kept it is not a change.
UPSERT_TRIAL_SQL = """
insert into trial (nct_id, title, phase, status, start_date, completion_date, sponsor, enrolment, enrolment_type,
                   has_results, results_posted_on, last_update_on, fetched_at)
values (%(nct_id)s, %(title)s, %(phase)s, %(status)s, %(start_date)s, %(completion_date)s, %(sponsor)s,
        %(enrolment)s, %(enrolment_type)s, %(has_results)s, %(results_posted_on)s, %(last_update_on)s, now())
on conflict (nct_id) do update set
  title = excluded.title, phase = excluded.phase, status = excluded.status,
  previous_status   = case when trial.status is distinct from excluded.status then trial.status
                           else trial.previous_status end,
  status_changed_on = case when trial.status is distinct from excluded.status
                           then (now() at time zone 'Africa/Cairo')::date else trial.status_changed_on end,
  start_date = excluded.start_date, completion_date = excluded.completion_date, sponsor = excluded.sponsor,
  enrolment = excluded.enrolment, enrolment_type = excluded.enrolment_type, has_results = excluded.has_results,
  results_posted_on = excluded.results_posted_on, last_update_on = excluded.last_update_on, fetched_at = now()
"""

DELETE_EVENTS_SQL = "delete from trial_event where nct_id = %(nct_id)s"

INSERT_EVENTS_SQL = """
insert into trial_event (nct_id, serious, term, organ_system, affected, at_risk, groups)
select %(nct_id)s, (e ->> 'serious')::boolean, e ->> 'term', e ->> 'organ_system', (e ->> 'affected')::int,
       (e ->> 'at_risk')::int, e -> 'groups'
  from jsonb_array_elements(%(events)s::jsonb) e
"""

# Only studies that are kept are linked: one that failed to fetch waits for the next run.
LINK_SQL = """
insert into trial_ingredient (ingredient_id, nct_id)
select %(i)s::uuid, t.nct_id from trial t where t.nct_id = any(%(ids)s)
on conflict do nothing
"""

UNLINK_SQL = "delete from trial_ingredient where ingredient_id = %(i)s::uuid and not (nct_id = any(%(ids)s))"

SEARCHED_SQL = """
insert into trial_search (ingredient_id, names, trials, searched_at)
values (%(i)s::uuid, %(names)s, (select count(*) from trial_ingredient where ingredient_id = %(i)s::uuid), now())
on conflict (ingredient_id) do update set names = excluded.names, trials = excluded.trials,
                                          searched_at = excluded.searched_at
"""

ORPHANS_SQL = """
delete from trial t where not exists (select 1 from trial_ingredient ti where ti.nct_id = t.nct_id)
"""

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/+-]*$")


def names(inn: str, terms: list[str]) -> list[str]:
    """The names searched: the English name first, then the other English names that are plain words (four
    letters or more, Latin script), each once whatever its case."""
    out: list[str] = []
    seen: set[str] = set()
    for i, n in enumerate([inn, *sorted(terms or [])]):
        n = " ".join((n or "").replace('"', " ").split())
        if not n or n.casefold() in seen or not _SAFE_NAME.match(n) or (i and len(n) < 4):
            continue
        seen.add(n.casefold())
        out.append(n)
    return out[:MAX_NAMES]


def expression(found: list[str]) -> str:
    """One search for all the names: "carvedilol" OR "Coreg". Quoted, so a name with a space or a word like
    AND stays one name."""
    return " OR ".join(f'"{n}"' for n in found)


def _day(s: Any) -> str | None:
    """A full day as published ("2025-04-23"), else None."""
    s = (s or "") if isinstance(s, str) else ""
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None


def _month_or_day(s: Any) -> str | None:
    """A start or completion date as published: a day or a month ("2005-11")."""
    s = (s or "") if isinstance(s, str) else ""
    return s if re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", s) else None


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _ident(study: dict) -> tuple[str | None, str | None]:
    p = study.get("protocolSection") or {}
    nct = ((p.get("identificationModule") or {}).get("nctId") or "").strip()
    last = _day(((p.get("statusModule") or {}).get("lastUpdatePostDateStruct") or {}).get("date"))
    return (nct if re.fullmatch(r"NCT\d{8}", nct) else None), last


def events(module: dict | None) -> list[dict]:
    """The serious and other adverse events of a study's results, one row per term and organ system (summed
    over the groups, and over the rows a sponsor gave the same term twice), with each group's numbers."""
    module = module or {}
    titles = {g.get("id"): (g.get("title") or "").strip() for g in module.get("eventGroups") or []}
    rows: dict[tuple[bool, str, str], dict] = {}
    for serious, key in ((True, "seriousEvents"), (False, "otherEvents")):
        for e in module.get(key) or []:
            term = " ".join((e.get("term") or "").split())
            if not term:
                continue
            organ = " ".join((e.get("organSystem") or "").split())
            row = rows.setdefault((serious, term, organ), {"serious": serious, "term": term, "organ_system": organ,
                                                           "groups": {}})
            for s in e.get("stats") or []:
                gid = s.get("groupId")
                g = row["groups"].setdefault(gid, {"group": titles.get(gid) or gid or "", "affected": 0,
                                                   "at_risk": None})
                g["affected"] += _int(s.get("numAffected")) or 0
                risk = _int(s.get("numAtRisk"))
                if risk is not None:      # the same people at risk, whichever row of the term gives them
                    g["at_risk"] = max(g["at_risk"] or 0, risk)
    out = []
    for row in rows.values():
        groups = list(row.pop("groups").values())
        risks = [g["at_risk"] for g in groups if g["at_risk"] is not None]
        out.append({**row, "affected": sum(g["affected"] for g in groups),
                    "at_risk": sum(risks) if risks else None, "groups": groups})
    return out


def parse_study(study: dict) -> dict | None:
    """What PHAROS keeps of one study, or None without an NCT id."""
    nct, last = _ident(study)
    if not nct:
        return None
    p = study.get("protocolSection") or {}
    status = p.get("statusModule") or {}
    design = p.get("designModule") or {}
    enrol = design.get("enrollmentInfo") or {}
    title = " ".join(((p.get("identificationModule") or {}).get("briefTitle") or "").split())
    phases = [str(x) for x in design.get("phases") or [] if x]
    module = (study.get("resultsSection") or {}).get("adverseEventsModule")
    return {
        "nct_id": nct,
        "title": title or nct,
        "phase": phases or None,
        "status": (status.get("overallStatus") or "UNKNOWN").strip() or "UNKNOWN",
        "start_date": _month_or_day((status.get("startDateStruct") or {}).get("date")),
        "completion_date": _month_or_day((status.get("completionDateStruct") or {}).get("date")),
        "sponsor": ((p.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name") or None,
        "enrolment": _int(enrol.get("count")),
        "enrolment_type": (enrol.get("type") or None),
        "has_results": bool(study.get("hasResults")),
        "results_posted_on": _day((status.get("resultsFirstPostDateStruct") or {}).get("date")),
        "last_update_on": last,
        "events": events(module),
    }


def _pages(get: Get, params: dict) -> tuple[list[dict], bool]:
    """Every study of a search, page by page; and whether every page was read."""
    studies: list[dict] = []
    token = None
    for _ in range(MAX_PAGES):
        got = get({**params, **({"pageToken": token} if token else {})})
        studies.extend(got.get("studies") or [])
        token = got.get("nextPageToken")
        if not token:
            return studies, True
    return studies, False


def search(get: Get, expr: str) -> tuple[dict[str, str | None], bool]:
    """NCT id -> last update day of every study whose interventions match; and whether the list is whole."""
    studies, whole = _pages(get, {"query.intr": expr, "fields": LIST_FIELDS, "pageSize": LIST_PAGE})
    found: dict[str, str | None] = {}
    for s in studies:
        nct, last = _ident(s)
        if nct:
            found[nct] = last
    return found, whole


def fetch(get: Get, ids: list[str]) -> list[dict]:
    """The full record of each study asked for (100 at a time)."""
    out = []
    for i in range(0, len(ids), FETCH_BATCH):
        batch = ids[i:i + FETCH_BATCH]
        studies, _ = _pages(get, {"filter.ids": ",".join(batch), "fields": STUDY_FIELDS, "pageSize": FETCH_BATCH})
        wanted = set(batch)
        out.extend(t for t in (parse_study(s) for s in studies) if t and t["nct_id"] in wanted)
    return out


def store(db: Any, trial: dict) -> None:
    """Keep one study and replace its adverse events, together."""
    row = {k: v for k, v in trial.items() if k != "events"}
    with db.transaction():
        db.execute(UPSERT_TRIAL_SQL, row)
        db.execute(DELETE_EVENTS_SQL, {"nct_id": trial["nct_id"]})
        if trial["events"]:
            db.execute(INSERT_EVENTS_SQL, {"nct_id": trial["nct_id"], "events": json.dumps(trial["events"])})


class _Busy(Exception):
    """Too many requests, or a server error: worth asking again after a wait."""


def _getter(client: Any) -> Get:
    import httpx

    last = [0.0]

    def get(params: dict) -> dict:
        for attempt in range(3):
            wait = GAP_S - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
            try:
                res = client.get(API, params=params)
                if res.status_code == 429 or res.status_code >= 500:
                    raise _Busy(f"HTTP {res.status_code}")
                res.raise_for_status()        # a refused question (400) is not asked again
                return res.json()
            except (_Busy, httpx.TransportError):
                if attempt == 2:
                    raise
                time.sleep(10 * (attempt + 1))
        raise _Busy("no answer")

    return get


def run(db: Any, get: Get | None = None) -> str:
    """Search, fetch what changed, link and unlink, for every active ingredient; what was done, in words."""
    ingredients = db.fetchall(INGREDIENTS_SQL)
    if not ingredients:
        return "no active ingredient"
    client = None
    if get is None:
        import httpx

        client = httpx.Client(timeout=60, headers={"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"})
        get = _getter(client)
    done: set[str] = set()                # fetched in this run, for whichever ingredient
    searched = failed = fetched = unchanged = 0
    try:
        for ing in ingredients:
            searched_names = names(ing["inn_en"], ing["terms"])
            if not searched_names:
                continue
            try:
                found, whole = search(get, expression(searched_names))
                ids = sorted(found)
                known = {r["nct_id"]: r["last_update"] for r in db.fetchall(KNOWN_SQL, {"ids": ids})} if ids else {}
                stale = [n for n in ids if n not in done and (n not in known or known[n] != found[n])]
                unchanged += sum(1 for n in ids if n in known and n not in stale and n not in done)
                for trial in fetch(get, stale):
                    store(db, trial)
                    done.add(trial["nct_id"])
                    fetched += 1
                with db.transaction():
                    if ids:
                        db.execute(LINK_SQL, {"i": ing["id"], "ids": ids})
                    if whole:
                        db.execute(UNLINK_SQL, {"i": ing["id"], "ids": ids})
                    db.execute(SEARCHED_SQL, {"i": ing["id"], "names": searched_names})
                searched += 1
            except Exception as exc:      # one ingredient never stops the others
                failed += 1
                log.warning("Clinical trials: one ingredient's search failed (%s)", type(exc).__name__)
        db.execute(ORPHANS_SQL)          # a study no ingredient links any more
    finally:
        if client is not None:
            client.close()
    words = f"{searched} ingredients searched, {fetched} studies fetched, {unchanged} unchanged"
    return words + (f", {failed} to try again" if failed else "")


def main(argv: list[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(prog="python -m collectors.trials", description=__doc__.split("\n\n")[0]).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from collectors.core.context import install_log_redaction

    install_log_redaction()   # the run logs are public: no request address (an ingredient's name) is printed
    from collectors.core.db import Db

    db = Db()
    try:
        words = run(db)
    finally:
        db.close()
    print("trials:", words)
    # Every search failed (the API is down or changed): the run fails, so it shows red on Actions.
    return 1 if words.startswith("0 ingredients searched") and "to try again" in words else 0


if __name__ == "__main__":
    sys.exit(main())
