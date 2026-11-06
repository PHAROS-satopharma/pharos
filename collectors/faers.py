"""FDA adverse-event report counts per watched ingredient (openFDA FAERS, migration 0071).

    python -m collectors.faers [--force] [--ingredient ID] [--minutes 45]

FAERS, the FDA Adverse Event Reporting System, holds the reports of suspected side effects that reach the FDA from
the United States and abroad. openFDA (https://open.fda.gov/apis/drug/event/) publishes them and counts them with its
``count=`` parameter, so no report is ever downloaded: only numbers come back.

For each active ingredient, over the last 8 complete calendar quarters openFDA holds (by ``receivedate``, the day FDA
received the report):

- the reports naming the ingredient, per quarter: one ``count=receivedate`` request, added up by quarter (a report has
  one receive date, so the quarters add up to the whole period);
- the reactions of those reports (MedDRA preferred terms, kept exactly as FDA gives them, never coded), for the whole
  period and for each quarter; the 100 most frequent of the whole period are kept;
- the same for every drug together, asked once a run for all the ingredients; a reaction outside every drug's most
  frequent is searched on its own.

``disproportion`` turns the whole period's counts into PRR and ROR with their 95% confidence intervals and the
chi-squared test. ``outliers`` flags a reaction that stands out in the ingredient's own profile: at least 3 reports,
the lower end of its PRR's interval at least 2 and its PRR at least twice the median PRR of the ingredient's kept
reactions. Evans' criteria (3 reports, PRR 2, chi-squared 4) flagged 88 of paracetamol's 100 on 6 Nov 2026: reports
of a drug often taken with others name more reactions than FDA's average report, so fatigue or nausea pass. The rule
is PHAROS's own, not a published standard. A flag is a reason to look, not a finding: the Ingredients screen shows it
beside the label.

How an ingredient is found (checked on the live API, 6 Nov 2026). The INN in upper case is searched, exactly, in
three fields at once (and its US name with it, RxNorm's name for the ingredient's rxcui, when that differs: FDA files
paracetamol as ACETAMINOPHEN, 100,540 reports, and has none under PARACETAMOL): ``patient.drug.openfda.generic_name`` and ``substance_name`` (filled only for a product FDA could
match to a US label: carvedilol 136,140 reports in each, lornoxicam, not sold in the US, none) and
``patient.drug.activesubstance.activesubstancename`` (the substance as FAERS coded it, also for foreign products:
lornoxicam 396). Together carvedilol has 142,304. An exact search takes the whole value only, so a salt written
with the substance ("CARVEDILOL PHOSPHATE", 2,975 reports) is not counted. When RxNorm does not answer, the
ingredient is left for the next run rather than counted under its INN alone.

A reaction is searched on its own by its exact name, but openFDA refuses some characters even in quotes (HTTP 400):
FDA writes an apostrophe as ^ ("WERNICKE^S ENCEPHALOPATHY"). Such a reaction's words are searched as a phrase and
its own count is read from those reports' reactions (152, the same as the exact count).

openFDA answers 404 "No matches found" for nothing found (a zero, not a failure), refuses a ``count`` longer than 100
without a key (403 API_KEY_MISSING), and has bad moments (a dropped connection, HTTP 500): every request is paced
(240 a minute with ``OPENFDA_API_KEY``, 40 without) and asked again after 429 or a server error. FAERS changes once
a quarter, so an ingredient counted in the last 6 days is left until ``--force``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Callable

log = logging.getLogger("collectors.faers")

API = "https://api.fda.gov/drug/event.json"
REACTION = "patient.reaction.reactionmeddrapt.exact"
REACTION_WORDS = "patient.reaction.reactionmeddrapt"      # the same, analysed: searched by its words
# the drugs a report names, by the substance FAERS coded: openfda.generic_name is filled only when FDA matched the
# product to a US label, and never named relugolix (Orgovyx) in carvedilol's 239 HOT FLUSH reports; this names it in 201 (6 Nov)
DRUG = "patient.drug.activesubstance.activesubstancename.exact"
NAME_FIELDS = (
    "patient.drug.openfda.generic_name.exact",
    "patient.drug.openfda.substance_name.exact",
    "patient.drug.activesubstance.activesubstancename.exact",
)
QUARTERS = 8
KEEP = 100                     # reactions kept per ingredient
CO_LIST = 25                   # drugs asked for with a flagged reaction
CO_MIN, CO_LIFT = 3, 2.0       # a drug shown with a flag: in 3 of its reports, and twice its usual share
FRESH_DAYS = 6
WAITS = (5, 15, 35)            # seconds before asking again after 429, a server error or a dropped connection
RETRY = {0, 429, 500, 502, 503, 504}
Z = 1.959964                   # the 97.5th centile of the normal distribution: a 95% interval

Getter = Callable[[dict[str, str]], tuple[int, Any]]


# ───────────────────────────── the arithmetic ─────────────────────────────
@dataclass(frozen=True)
class Disproportion:
    prr: float | None
    prr_low: float | None
    prr_high: float | None
    ror: float | None
    ror_low: float | None
    ror_high: float | None
    chi2: float | None


def disproportion(a: int, b: int, c: int, d: int) -> Disproportion:
    """The 2×2 table of one reaction: a = reports of the ingredient with the reaction, b = of the ingredient without
    it, c = of every other drug with it, d = of every other drug without it.

    PRR = [a/(a+b)] / [c/(c+d)], ROR = ad/bc, each with the 95% interval of its logarithm; chi-squared with Yates'
    correction. No continuity correction is added: a value that would divide by zero is None (PRR and ROR when c is
    0, ROR when b is 0), and so is an interval whose logarithm is not defined (a is 0, or d for the ROR).
    """
    if min(a, b, c, d) < 0:
        raise ValueError("a count cannot be negative")
    n = a + b + c + d
    prr = prr_low = prr_high = ror = ror_low = ror_high = chi2 = None
    if a + b and c:
        prr = (a / (a + b)) / (c / (c + d))
        if a:
            se = math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d))
            prr_low, prr_high = math.exp(math.log(prr) - Z * se), math.exp(math.log(prr) + Z * se)
    if b and c:
        ror = (a * d) / (b * c)
        if a and d:
            se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
            ror_low, ror_high = math.exp(math.log(ror) - Z * se), math.exp(math.log(ror) + Z * se)
    den = (a + b) * (c + d) * (a + c) * (b + d)
    if den:
        chi2 = n * max(0.0, abs(a * d - b * c) - n / 2) ** 2 / den
    return Disproportion(prr, prr_low, prr_high, ror, ror_low, ror_high, chi2)


def outliers(reactions: list[dict]) -> list[bool]:
    """Which of an ingredient's reactions stand out in its own profile: at least 3 reports, and either no other drug
    has the reaction (no PRR) or the lower end of its PRR's 95% interval is at least 2 and its PRR at least twice the
    median PRR of these reactions. A reaction without a PRR counts as the highest in the median."""
    if not reactions:
        return []
    bar = 2 * statistics.median(math.inf if x["prr"] is None else x["prr"] for x in reactions)
    return [x["reports"] >= 3 and (x["prr"] is None or (x["prr_low"] is not None and x["prr_low"] >= 2
                                                        and x["prr"] >= bar))
            for x in reactions]


# ───────────────────────────── quarters ─────────────────────────────
def quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def next_quarter(q: date) -> date:
    return date(q.year + 1, 1, 1) if q.month == 10 else date(q.year, q.month + 3, 1)


def previous_quarter(q: date) -> date:
    return date(q.year - 1, 10, 1) if q.month == 1 else date(q.year, q.month - 3, 1)


def quarter_end(q: date) -> date:
    return next_quarter(q) - timedelta(days=1)


def last_quarters(latest: date, n: int = QUARTERS) -> list[date]:
    """The first days of the last ``n`` complete quarters up to ``latest`` (openFDA's newest receive date), oldest
    first: a quarter whose last day openFDA does not hold yet is not complete."""
    q = quarter_start(latest)
    if quarter_end(q) != latest:
        q = previous_quarter(q)
    out = [q]
    while len(out) < n:
        out.insert(0, previous_quarter(out[0]))
    return out


def period(start: date, end: date) -> str:
    return f"receivedate:[{start:%Y%m%d} TO {end:%Y%m%d}]"


def _quoted(text: str) -> str:
    return '"' + " ".join(text.replace("\\", " ").replace('"', " ").split()) + '"'


def searched_names(inn: str, *others: str | None) -> list[str]:
    """The INN and any other name (the US one), in capitals, each once."""
    out: list[str] = []
    for n in (inn, *others):
        n = " ".join((n or "").upper().split())
        if n and n not in out:
            out.append(n)
    return out


def name_search(inn: str, *others: str | None) -> str:
    """The INN and its US name when it differs, in upper case, exactly, in the three fields that name a drug's
    substance."""
    return "(" + " ".join(f"{f}:{_quoted(n)}" for f in NAME_FIELDS for n in searched_names(inn, *others)) + ")"


# ───────────────────────────── openFDA ─────────────────────────────
class OpenFdaError(Exception):
    def __init__(self, status: int, said: str = "") -> None:
        super().__init__(f"openFDA answered HTTP {status}" + (f" ({said})" if said else ""))
        self.status = status


def _said(body: Any) -> str:
    """openFDA's own words for an error ({"error": {"code", "message"}}), or ""."""
    err = (body or {}).get("error") if isinstance(body, dict) else None
    return " ".join(str((err or {}).get(k) or "") for k in ("code", "message")).strip()[:200]


class OpenFda:
    """Paced, retried requests to the drug/event endpoint. ``get`` takes the query parameters and gives back the
    HTTP status and the decoded JSON (status 0 for a dropped connection)."""

    def __init__(self, get: Getter, key: str | None = None, *, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.get, self.key, self.sleep, self.clock = get, key, sleep, clock
        self.gap = 60 / 240 if key else 60 / 40
        self.limit = 1000 if key else 100        # a longer count needs a key (403 API_KEY_MISSING)
        self.requests = 0
        self._last: float | None = None

    def ask(self, **params: str) -> dict | None:
        """The answer, or None for openFDA's 404 "No matches found"."""
        if self.key:
            params["api_key"] = self.key
        for attempt in range(len(WAITS) + 1):
            if self._last is not None:
                wait = self.gap - (self.clock() - self._last)
                if wait > 0:
                    self.sleep(wait)
            self._last = self.clock()
            self.requests += 1
            status, body = self.get(params)
            if status == 200:
                return body
            if status == 404:
                return None
            if status == 403 and self.key and "API_KEY_INVALID" in _said(body):
                # openFDA refused the key: count on without it, at the keyless pace, rather than not at all.
                log.warning("FAERS: openFDA refused OPENFDA_API_KEY (API_KEY_INVALID); counting without a key")
                self.key, self.gap, self.limit = None, 60 / 40, 100
                params.pop("api_key", None)
                if params.get("limit") == "1000":
                    params["limit"] = "100"
                continue
            if status in RETRY and attempt < len(WAITS):
                self.sleep(WAITS[attempt])
                continue
            raise OpenFdaError(status, _said(body))
        raise AssertionError("unreachable")

    def days(self, search: str) -> dict[date, int]:
        """Reports per receive date."""
        body = self.ask(search=search, count="receivedate") or {}
        out: dict[date, int] = {}
        for r in body.get("results") or []:
            t = str(r.get("time") or "")
            if re.fullmatch(r"\d{8}", t):
                out[date(int(t[:4]), int(t[4:6]), int(t[6:]))] = int(r.get("count") or 0)
        return out

    def reactions(self, search: str) -> tuple[dict[str, int], bool]:
        """Reports per reaction, the most frequent first, and whether the list holds every reaction (it is shorter
        than the longest list openFDA gives)."""
        body = self.ask(search=search, count=REACTION, limit=str(self.limit)) or {}
        rows = body.get("results") or []
        return {str(r["term"]): int(r.get("count") or 0) for r in rows if r.get("term")}, len(rows) < self.limit

    def drugs(self, search: str, limit: int) -> tuple[dict[str, int], bool]:
        """Reports per active substance of the drugs they name, the most frequent first, as FAERS writes them (a
        combination's substances joined with a backslash, "SACUBITRIL\\VALSARTAN"), and whether the list holds every
        drug (it is shorter than the limit, or than the 100 a refused key leaves)."""
        body = self.ask(search=search, count=DRUG, limit=str(limit)) or {}
        rows = body.get("results") or []
        whole = len(rows) < min(limit, self.limit)
        return {str(r["term"]): int(r.get("count") or 0) for r in rows if r.get("term")}, whole

    def total(self, search: str) -> int:
        body = self.ask(search=search, limit="1")
        return int((((body or {}).get("meta") or {}).get("results") or {}).get("total") or 0)


def http_getter(client: Any) -> Getter:
    """The real getter, over an ``httpx.Client``. A request address carries the key: it is never logged."""
    import httpx

    def get(params: dict[str, str]) -> tuple[int, Any]:
        try:
            res = client.get(API, params=params)
        except httpx.TransportError:
            return 0, None
        try:
            return res.status_code, res.json()
        except ValueError:
            return res.status_code, None

    return get


def by_quarter(days: dict[date, int], quarters: list[date]) -> dict[date, int]:
    out = {q: 0 for q in quarters}
    for d, n in days.items():
        q = quarter_start(d)
        if q in out:
            out[q] += n
    return out


class Background:
    """Every drug together, for every ingredient of a run: the reports per quarter, and the reactions of the whole
    period and of each quarter, each asked once."""

    def __init__(self, api: OpenFda, today: date | None = None) -> None:
        today = today or date.today()
        first = quarter_start(today)
        for _ in range(QUARTERS + 2):
            first = previous_quarter(first)
        days = api.days(period(first, today))
        if not days:
            raise OpenFdaError(404, "no report in the last two and a half years")
        self.api = api
        self.quarters = last_quarters(max(days))
        self.whole = period(self.quarters[0], quarter_end(self.quarters[-1]))
        self.reports = by_quarter(days, self.quarters)
        self._lists: dict[date | None, tuple[dict[str, int], bool]] = {}
        self._alone: dict[str, int] = {}

    def _list(self, q: date | None) -> tuple[dict[str, int], bool]:
        if q not in self._lists:
            self._lists[q] = self.api.reactions(self.whole if q is None else period(q, quarter_end(q)))
        return self._lists[q]

    def whole_count(self, reaction: str) -> int:
        """Reports of every drug with the reaction in the whole period: from the most frequent list, else searched."""
        counts, complete = self._list(None)
        if reaction in counts:
            return counts[reaction]
        if complete:
            return 0
        if reaction not in self._alone:
            self._alone[reaction] = self._searched(reaction)
        return self._alone[reaction]

    def _searched(self, reaction: str) -> int:
        try:
            return self.api.total(f"{REACTION}:{_quoted(reaction)} AND {self.whole}")
        except OpenFdaError as exc:
            if exc.status != 400:
                raise
        # openFDA refuses some characters even in quotes (FDA writes an apostrophe as ^: "WERNICKE^S
        # ENCEPHALOPATHY"). Its words as a phrase find the reports, and their count by exact reaction gives its own.
        words = " ".join(re.sub(r"[^0-9A-Za-z]+", " ", reaction).split())
        if not words:
            return 0
        counts, _ = self.api.reactions(f"{REACTION_WORDS}:{_quoted(words)} AND {self.whole}")
        return counts.get(reaction, 0)

    def quarter_count(self, q: date, reaction: str) -> int | None:
        """Reports of every drug with the reaction in one quarter, or None when it is below the list."""
        counts, complete = self._list(q)
        return counts.get(reaction, 0 if complete else None)


def reaction_search(reaction: str) -> str:
    """The reaction by its exact name; one with a character openFDA refuses even in quotes (FDA writes an apostrophe
    as ^) by its words as a phrase, as Background._searched does."""
    if re.fullmatch(r"[0-9A-Za-z ,()/.-]+", reaction):
        return f"{REACTION}:{_quoted(reaction)}"
    return f"{REACTION_WORDS}:{_quoted(' '.join(re.sub(r'[^0-9A-Za-z]+', ' ', reaction).split()))}"


class UsualDrugs:
    """How many of an ingredient's reports over the whole period name each other drug: the base a drug's share of one
    reaction's reports is weighed against. One list a run, asked only when a flagged reaction needs it; a drug
    missing from a list too long to be whole is counted on its own."""

    def __init__(self, api: OpenFda, names: str, whole: str) -> None:
        self.api, self.names, self.whole = api, names, whole
        self.listed: dict[str, int] | None = None
        self.complete = True

    def count(self, term: str) -> int | None:
        if self.listed is None:
            self.listed, self.complete = self.api.drugs(f"{self.names} AND {self.whole}", self.api.limit)
        if term in self.listed:
            return self.listed[term]
        if self.complete or "\\" in term:          # a backslash cannot be searched exactly
            return None
        return self.api.total(f"{self.names} AND {DRUG}:{_quoted(term)} AND {self.whole}")


def co_drug(api: OpenFda, names: str, own: list[str], reaction: str, whole: str, reports: int, n_drug: int,
            usual: UsualDrugs) -> tuple[str | None, int | None, int | None]:
    """The other drug over-represented in the reports of the ingredient with the reaction (0078): named in at least
    CO_MIN of them, and in a share of them at least CO_LIFT times its share of all the ingredient's reports. The most
    reported such drug, in how many of the reaction's reports, and in how many of all the ingredient's. A drug taken
    with the ingredient can be what the reaction is reported for (0076); one often taken with it anyway (aspirin
    with carvedilol) explains nothing. The ingredient under any of its names, its salts and the combinations that
    hold it are never the answer."""
    mine = [re.compile(r"\b" + re.escape(n) + r"\b") for n in own]
    try:
        named, _ = api.drugs(f"{names} AND {reaction_search(reaction)} AND {whole}", CO_LIST)
    except OpenFdaError as exc:
        if exc.status != 400:
            raise
        return None, None, None              # never lose the ingredient's counts over one reaction's lookup
    others = sorted((-n, t) for t, n in named.items() if n >= CO_MIN and not any(m.search(t.upper()) for m in mine))
    for minus_n, term in others:                                 # the most reported first, then by name
        n, base = -minus_n, usual.count(term)
        if not base or not reports or not n_drug:
            continue
        base = max(base, n)                  # never fewer than the reaction's own (the lists can drift)
        if n * n_drug >= CO_LIFT * reports * base:
            return " + ".join(p.strip() for p in term.split("\\") if p.strip()), n, base
    return None, None, None


def count_ingredient(api: OpenFda, bg: Background, inn: str, us_name: str | None = None) -> dict:
    """Everything kept for one ingredient: the reports per quarter, and its most frequent reactions with their
    quarters and their disproportion. ``us_name`` (RxNorm's) is searched too when it differs from the INN."""
    names = name_search(inn, us_name)
    days = api.days(f"{names} AND {bg.whole}")
    per_q = by_quarter(days, bg.quarters)
    n_drug = sum(per_q.values())
    n_all = sum(bg.reports.values())
    whole, _ = api.reactions(f"{names} AND {bg.whole}") if n_drug else ({}, True)
    top = sorted(whole.items(), key=lambda kv: (-kv[1], kv[0]))[:KEEP]
    quarters, counts = [], []
    for q in bg.quarters:
        listed, complete = (api.reactions(f"{names} AND {period(q, quarter_end(q))}") if per_q[q] and top
                            else ({}, True))
        quarters.append({"quarter": q.isoformat(), "reports": per_q[q], "all_reports": bg.reports[q],
                         "complete": complete})
        for reaction, _n in top:
            if reaction in listed:
                counts.append({"quarter": q.isoformat(), "reaction": reaction, "reports": listed[reaction],
                               "all_reports": bg.quarter_count(q, reaction)})
    reactions = []
    for reaction, a in top:
        all_r = max(bg.whole_count(reaction), a)     # never fewer than the ingredient's own (the lists can drift)
        b, c = n_drug - a, all_r - a
        stats = disproportion(a, b, c, max(n_all - n_drug - c, 0))
        reactions.append({"reaction": reaction, "reports": a, "all_reports": all_r, **asdict(stats),
                          "co_drug": None, "co_reports": None, "co_all_reports": None})
    usual = UsualDrugs(api, names, bg.whole)
    for x, flag in zip(reactions, outliers(reactions), strict=True):
        x["flagged"] = flag
        if flag:
            x["co_drug"], x["co_reports"], x["co_all_reports"] = co_drug(
                api, names, searched_names(inn, us_name), x["reaction"], bg.whole, x["reports"], n_drug, usual)
    return {"searched": ", ".join(searched_names(inn, us_name)), "first_quarter": bg.quarters[0].isoformat(),
            "last_quarter": bg.quarters[-1].isoformat(), "reports": n_drug, "all_reports": n_all,
            "quarters": quarters, "reactions": reactions, "counts": counts}


# ───────────────────────────── the database ─────────────────────────────
WAITING_SQL = """
select i.id::text as id, i.inn_en, i.rxcui
  from ingredient i
  left join faers_ingredient f on f.ingredient_id = i.id
 where i.active
   and (%(force)s or f.fetched_at is null or f.fetched_at < now() - make_interval(days => %(fresh)s))
   and (%(one)s::uuid is null or i.id = %(one)s::uuid)
 order by f.fetched_at nulls first, i.inn_en
"""

FRESH_SQL = """
select count(*)::int as n from ingredient i join faers_ingredient f on f.ingredient_id = i.id
 where i.active and f.fetched_at >= now() - make_interval(days => %(fresh)s)
"""


def store(db: Any, ingredient: str, got: dict) -> None:
    with db.transaction():
        db.execute(
            """insert into faers_ingredient (ingredient_id, searched, first_quarter, last_quarter, reports, all_reports,
                                             fetched_at)
               values (%(i)s::uuid, %(s)s, %(f)s::date, %(l)s::date, %(n)s, %(a)s, now())
               on conflict (ingredient_id) do update set searched = excluded.searched,
                 first_quarter = excluded.first_quarter, last_quarter = excluded.last_quarter,
                 reports = excluded.reports, all_reports = excluded.all_reports, fetched_at = now()""",
            {"i": ingredient, "s": got["searched"], "f": got["first_quarter"], "l": got["last_quarter"],
             "n": got["reports"], "a": got["all_reports"]})
        # the counts of the last fetch go with their quarters and reactions
        db.execute("delete from faers_quarter where ingredient_id = %(i)s::uuid", {"i": ingredient})
        db.execute("delete from faers_reaction where ingredient_id = %(i)s::uuid", {"i": ingredient})
        db.execute(
            """insert into faers_quarter (ingredient_id, quarter, reports, all_reports, complete)
               select %(i)s::uuid, x.quarter, x.reports, x.all_reports, x.complete
                 from jsonb_to_recordset(%(q)s::jsonb) x(quarter date, reports int, all_reports int, complete boolean)""",
            {"i": ingredient, "q": json.dumps(got["quarters"])})
        if got["reactions"]:
            db.execute(
                """insert into faers_reaction (ingredient_id, reaction, reports, all_reports, prr, prr_low, prr_high,
                                               ror, ror_low, ror_high, chi2, flagged, co_drug, co_reports,
                                               co_all_reports)
                   select %(i)s::uuid, x.reaction, x.reports, x.all_reports, x.prr, x.prr_low, x.prr_high, x.ror,
                          x.ror_low, x.ror_high, x.chi2, x.flagged, x.co_drug, x.co_reports,
                          x.co_all_reports
                     from jsonb_to_recordset(%(r)s::jsonb) x(reaction text, reports int, all_reports int, prr float8,
                          prr_low float8, prr_high float8, ror float8, ror_low float8, ror_high float8, chi2 float8,
                          flagged boolean, co_drug text, co_reports int, co_all_reports int)""",
                {"i": ingredient, "r": json.dumps(got["reactions"])})
        if got["counts"]:
            db.execute(
                """insert into faers_count (ingredient_id, quarter, reaction, reports, all_reports)
                   select %(i)s::uuid, x.quarter, x.reaction, x.reports, x.all_reports
                     from jsonb_to_recordset(%(c)s::jsonb) x(quarter date, reaction text, reports int, all_reports int)""",
                {"i": ingredient, "c": json.dumps(got["counts"])})


def count_reports(db: Any, api: OpenFda, *, force: bool = False, ingredient: str | None = None,
                  minutes: float = 45, today: date | None = None, clock: Callable[[], float] = time.monotonic,
                  us_name: Callable[[str], str | None] | None = None) -> str:
    """Count every ingredient waiting for its FAERS counts; what was done, in words. The run logs are public: no
    ingredient is named in them, only numbers. ``us_name`` gives RxNorm's name of an ingredient's rxcui; when it
    fails the ingredient is left for the next run, since its INN alone can find none of its reports."""
    rows = db.fetchall(WAITING_SQL, {"force": force, "fresh": FRESH_DAYS, "one": ingredient})
    fresh = 0 if force else (db.fetchone(FRESH_SQL, {"fresh": FRESH_DAYS}) or {}).get("n", 0)
    later = f", {fresh} counted in the last {FRESH_DAYS} days" if fresh else ""
    if not rows:
        return "no ingredient waits for its FAERS counts" + later
    bg = Background(api, today)
    stop = clock() + minutes * 60
    counted = none = failed = left = 0
    for r in rows:
        if clock() > stop:
            left += 1
            continue
        try:
            us = us_name(r["rxcui"]) if us_name and r.get("rxcui") else None
            if us_name and r.get("rxcui") and not us:
                raise LookupError("RxNorm gave no name for the ingredient's rxcui")   # left for the next run
            got = count_ingredient(api, bg, r["inn_en"], us)
            store(db, r["id"], got)
        except Exception as exc:              # one ingredient never stops the others
            failed += 1
            log.warning("FAERS: an ingredient failed (%s)",
                        f"HTTP {exc.status}" if isinstance(exc, OpenFdaError) else type(exc).__name__)
            continue
        counted += 1
        none += not got["reports"]
    q0, q1 = bg.quarters[0], bg.quarters[-1]
    words = (f"{counted} ingredients counted ({none} with no report) for {q0:%b %Y} to {quarter_end(q1):%b %Y}"
             + later + (f", {failed} to try again" if failed else "")
             + (f", {left} left for the next run" if left else ""))
    return words + f"; {api.requests} requests to openFDA"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.faers", description=__doc__.split("\n\n")[0])
    p.add_argument("--force", action="store_true", help=f"count even an ingredient counted in the last {FRESH_DAYS} days")
    p.add_argument("--ingredient", help="count this ingredient only (its id)")
    p.add_argument("--minutes", type=float, default=45, help="start no ingredient after this many minutes")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.ingredient and not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                                            args.ingredient):
        p.error("--ingredient takes an ingredient id")

    import httpx

    from collectors.core.context import install_log_redaction
    from collectors.core.db import Db
    from collectors.coding.drugs import RxNav

    install_log_redaction()   # the request addresses carry the key and the ingredient: never printed
    key = os.environ.get("OPENFDA_API_KEY", "").strip() or None     # a pasted secret can carry a newline
    db = Db()
    try:
        with httpx.Client(timeout=90, headers={"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"}) as client:
            api = OpenFda(http_getter(client), key)
            rx = RxNav()
            print("faers:", count_reports(db, api, force=args.force, ingredient=args.ingredient, minutes=args.minutes,
                                          us_name=rx.name))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
