"""NCBI literature watch (E-utilities): PubMed AND PubMed Central, daily, for every active ingredient.

Searches. Per active ingredient, each typed exactly as a person types it into the NCBI search box (unquoted, no
field tag, so NCBI's automatic term mapping expands it as its websites do):
  name   the English INN (``ingredient.inn_en``)
  class  each English word of the ingredient's drug classes (``class_term`` rows in English) that are searched
         and in the literature (``ingredient_class.enabled`` and ``.literature``, 0049 and 0051)
Each search runs on ``db=pubmed`` and on ``db=pmc`` (full texts), by Entrez (entry) date, so a paper added late
with an old publication date is still found. esearch is paged with ``retstart`` until every id is in; a window
holding more ids than esearch serves for one search (9,999) is split in halves, and a single day over that is
cut there and logged. esummary then reads the papers in batches of 200; a paper already stored is not read again,
so ``items`` (and the screening log's "seen") are the papers new to PHAROS.

One paper, one item. A paper found in both databases is stored once, under its PMID (the PMC record's
``articleids`` give it), with both links in ``structured`` (``pubmed_url``, ``pmc_url``). The item links to
PubMed when the PubMed search found it, otherwise to its PMC full text (where the words are). A PMC record with no
PMID yet is stored as ``PMC<n>``; ``aliases`` lets the runner recognise it when its PMID appears later. A paper
the Europe PMC watch stored first (``collectors/parsers/europepmc.py``; the same PMID, PMC id or DOI) is never
stored again: that document records that NCBI found it too (``collectors/parsers/_literature.py``).

``structured.query_term`` lists every search word that found the paper and is matched as a structured field, so
the paper is linked to its ingredient (a name search) or to its drug class (a class search).
``structured.queries`` keeps which search found it in which database, and ``structured.class_only`` is true when
only class words found it: like a regulator's class-wide notice, it never alerts at once and goes to the daily
class digest.

Case reports. The publication types (``pubtype``: "Case Reports", "Review" …) are in a paper's PubMed record
only, so for the papers PMC alone found the run reads their PubMed records too, by the PMID the PMC record
carries (``articleids``), in the same batches of 200. ``structured.case_report`` is ``{"reason": "pubtype"}``
when PubMed types the paper Case Reports, ``{"reason": "title"}`` when its title says "case report", "case
series" or "a case of" (the words of ``v_case_report``, migration 0031), else null. A paper not in PubMed yet
has no type, so only its title can say. The flag starts the reporting clock on the Ingredients screen (day zero
is the Cairo day PHAROS found the paper) and puts the paper in the daily message (``collectors/alerts.py``).

Windows. A search that has run before reads from the last complete run minus 3 days, or from its own last
search minus 3 days when that is earlier (a search switched off for a while: its paused days are caught up, as
new); at most 90 days back, and ``lookback_days`` before the source's first complete run. A search never run (a newly added ingredient or class
word, or one not run for 90 days) first looks back ``look_back_months`` (``class_look_back_months`` for a class
word) of entry dates, and what that look-back finds is history (``is_history``: stored without an alert or a
digest line, like a backfill). The ``literature_search`` table (migration 0035) remembers each search; a
look-back counts as done only once every paper it found is stored, so one cut short by the item cap or the time
budget continues on the next run (its days again as history, the days since as new). New papers are stored
first, then a look-back's name papers, then its class papers; at most ``max_new_items`` papers are read per run.
New papers over that cap make the run incomplete ("item cap reached: …"), so ``last_ok_at`` stays and the next
run reads the same days again; before 6 Nov 2026 the window moved on and those papers were never read.
A backfill (``--backfill``) reads every search's whole backfill window as history and leaves the table alone.

Options:
  terms                  list  name searches instead of the active ingredients (tests, one-off searches)
  lookback_days          int   default 10: the window before the source's first complete run
  look_back_months       int   default 12: a new search's look-back
  class_look_back_months int   default look_back_months: a new class word's look-back
  page_size              int   default 5000 ids per esearch page
  max_new_items          int   papers read (esummary) and stored per normal run (the runner caps it too)

Etiquette: ``tool=pharos``, ``NCBI_API_KEY`` when present, and at most 3 requests a second without a key (10 with
one). E-utilities answers HTTP 500/502/504 in bursts (on 2026-11-05 most esearch calls, from any network, while
esummary answered), or HTTP 200 with ``esearchresult.ERROR`` "Search Backend failed ... Search is temporarily
unavailable", so each call is retried after 5, 15, 30 and 60 s before the source fails (as down, never as "the
page changed shape"); HTTP 429 is waited out by the fetch layer. An answer without its id list, count or result
raises ParseError.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from collectors.parsers._literature import Elsewhere
from collectors.parsers.base import FetchContext, FetchError, Item, ParseError, SourceConfig, parse_date

log = logging.getLogger(__name__)

STRUCTURED_FIELDS = ["query_term"]

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
EUTILS_HOST = "eutils.ncbi.nlm.nih.gov"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{}/"
PMC_URL = "https://pmc.ncbi.nlm.nih.gov/articles/{}/"
DBS = ("pubmed", "pmc")
LANGS = {"eng": "en", "ger": "de", "fre": "fr", "ita": "it", "spa": "es", "por": "pt", "dut": "nl",
         "dan": "da", "swe": "sv", "nor": "nb", "fin": "fi", "ice": "is", "jpn": "ja", "kor": "ko",
         "ara": "ar", "chi": "zh", "rus": "ru", "pol": "pl", "tur": "tr"}
NCBI_RETRY_WAITS_S = (5.0, 15.0, 30.0, 60.0)
NCBI_FLAKY = (500, 502, 504)
OVERLAP_DAYS = 3
MAX_CATCH_UP_DAYS = 90
LOOK_BACK_MONTHS = 12
STALE_DAYS = 90               # a search not run for this long looks back again
MAX_IDS = 9_999               # esearch serves the first 9,999 ids of one search (PubMed refuses more)
PAGE_SIZE = 5_000
SUMMARY_BATCH = 200
MAX_NEW_ITEMS = 400           # the runner's default
GAP_NO_KEY_S = 0.34           # NCBI: at most 3 requests a second without an API key …
GAP_KEY_S = 0.11              # … and 10 with one
CASE_REPORT_TYPE = "Case Reports"
# the words of v_case_report (0031): \m and \M there, whole words here
CASE_REPORT_TITLE = re.compile(r"\b(case report|case reports|case series|a case of)\b", re.IGNORECASE)


def case_report(pubtype: list | None, title: str | None) -> dict | None:
    """``{"reason": "pubtype"}`` when PubMed types the paper Case Reports, ``{"reason": "title"}`` when only its
    title says so, else None."""
    if CASE_REPORT_TYPE in (pubtype or []):
        return {"reason": "pubtype"}
    if CASE_REPORT_TITLE.search(title or ""):
        return {"reason": "title"}
    return None


def _common() -> str:
    key = os.environ.get("NCBI_API_KEY")
    return "&tool=pharos" + (f"&api_key={key}" if key else "")


def _pace(ctx: FetchContext) -> None:
    """NCBI's own limit instead of the 2 s every other host gets: one run makes a few hundred calls."""
    gap = GAP_KEY_S if os.environ.get("NCBI_API_KEY") else GAP_NO_KEY_S
    if ctx.host_gap_s > gap:
        ctx._host_gap.setdefault(EUTILS_HOST, gap)


def _ncbi_error(data: object) -> str | None:
    """The message E-utilities sends with HTTP 200 while its search backend is down."""
    if not isinstance(data, dict):
        return None
    msg = (data.get("esearchresult") or {}).get("ERROR") or data.get("error")
    return str(msg) if msg else None


def _get_json(ctx: FetchContext, url: str) -> dict:
    """``url`` as JSON, waiting out E-utilities' passing server errors."""
    for wait in (*NCBI_RETRY_WAITS_S, None):
        try:
            # its own schedule below, longer than the fetcher's two retries (NCBI was down for hours)
            data = ctx.get(url, accept="application/json", retry_server_errors=False).json()
        except FetchError as exc:
            if wait is None or exc.status not in NCBI_FLAKY:
                raise
            why = f"HTTP {exc.status}"
        else:
            err = _ncbi_error(data)
            if err is None:
                return data
            if wait is None:
                # NCBI is down, not changed: a failed run, never "the page changed shape"
                raise FetchError(503, url, f"NCBI search unavailable: {err[:300]}")
            why = "search unavailable"
        log.info("NCBI %s: waiting %.0f s, then retrying", why, wait)
        ctx._sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


# ───────────────────────────── searches ─────────────────────────────

@dataclass(frozen=True)
class Search:
    query: str        # exactly as typed into the search box
    kind: str         # name | class
    db: str           # pubmed | pmc

    @property
    def key(self) -> tuple[str, str]:
        """Its ``literature_search`` row: NCBI ignores case."""
        return (self.db, self.query.lower())


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    history: bool     # a first look-back: what it finds is history


def _words(text: str) -> str:
    return " ".join(str(text or "").split())


def searches(names: Iterable[str], class_words: dict[str, list[str]]) -> list[Search]:
    """Name searches first, then the class words of those names: each word once (whatever its case), on
    both databases."""
    out: list[Search] = []
    seen: set[str] = set()

    def add(word: str, kind: str) -> None:
        q = _words(word)
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.extend(Search(q, kind, db) for db in DBS)

    names = [_words(n) for n in names]
    for n in names:
        add(n, "name")
    for n in names:
        for w in class_words.get(n) or []:
            add(w, "class")
    return out


def months_back(d: date, months: int) -> date:
    """The same day ``months`` earlier (the month's last day when it has fewer)."""
    y, m = divmod(d.year * 12 + d.month - 1 - months, 12)
    for dd in (d.day, 30, 29, 28):
        try:
            return date(y, m + 1, dd)
        except ValueError:
            continue
    raise AssertionError("unreachable")  # pragma: no cover


def _normal_start(ctx: FetchContext, opts: dict, today: date) -> date:
    """A search done before reads from the last complete run minus 3 days, at most 90 days back."""
    last_ok = getattr(ctx, "last_ok_at", None)
    if last_ok is not None:
        start = last_ok.date() - timedelta(days=OVERLAP_DAYS)
    else:
        start = today - timedelta(days=int(opts.get("lookback_days", 10)))
    return max(start, today - timedelta(days=MAX_CATCH_UP_DAYS))


def _caught_up(normal: Window, last_searched: datetime | None, today: date) -> Window:
    """The daily window, reaching back to the search's own last day less 3 days when that is earlier. A search
    switched off for a while (its ingredient paused, or its class word out of the literature) was not run while
    the source's other searches were, so the source's last complete run alone would skip its paused days; the
    days are read as new, as after an outage, and never more than 90 days back (past STALE_DAYS it looks back
    again instead)."""
    if last_searched is None:
        return normal
    own = max(last_searched.date() - timedelta(days=OVERLAP_DAYS), today - timedelta(days=MAX_CATCH_UP_DAYS))
    return Window(own, today, False) if own < normal.start else normal


def plan(ctx: FetchContext, search: Search, state: dict | None, opts: dict, today: date,
         remembered: bool) -> tuple[list[Window], dict]:
    """The windows ``search`` reads this run, and its ``literature_search`` row as it stands before this run
    (``done``: its look-back is complete)."""
    if ctx.backfill:
        start = today - timedelta(days=31 * int(getattr(ctx, "backfill_months", 12) or 12))
        return [Window(start, today, True)], {}
    normal = Window(_normal_start(ctx, opts, today), today, False)
    if not remembered:
        return [normal], {}           # nothing to remember searches in (--no-db, tests): what is new
    if state is not None:
        last = state.get("last_searched_at")
        if last is not None and last < datetime.now(timezone.utc) - timedelta(days=STALE_DAYS):
            state = None              # not run for months (its ingredient was switched off): look back again
    if state is None:
        months = int(opts.get("look_back_months", LOOK_BACK_MONTHS))
        if search.kind == "class":
            months = int(opts.get("class_look_back_months", months))
        start = months_back(today, months)
        return [Window(start, today, True)], {"look_back_from": start, "history_until": today, "done": False}
    row = {"look_back_from": state["look_back_from"], "history_until": state["history_until"],
           "done": state.get("look_back_done_at") is not None}
    if row["done"]:
        return [_caught_up(normal, state.get("last_searched_at"), today)], row
    # a look-back cut short: its days again as history, then what was entered since as new
    until = row["history_until"]
    windows = [Window(row["look_back_from"], until, True)]
    if until < today:
        windows.append(Window(max(until + timedelta(days=1), today - timedelta(days=MAX_CATCH_UP_DAYS)),
                              today, False))
    return windows, row


def _esearch_url(search: Search, start: date, end: date, retstart: int, retmax: int) -> str:
    return (f"{EUTILS}/esearch.fcgi?db={search.db}&retmode=json&datetype=edat"
            f"&mindate={start:%Y/%m/%d}&maxdate={end:%Y/%m/%d}&retstart={retstart}&retmax={retmax}"
            f"&term={quote(search.query, safe='')}{_common()}")


def esearch_ids(ctx: FetchContext, search: Search, start: date, end: date,
                page: int = PAGE_SIZE) -> list[str]:
    """Every id ``search`` finds among the entries of ``start``…``end`` (both included), page by page."""
    ids: list[str] = []
    retstart = 0
    while True:
        data = _get_json(ctx, _esearch_url(search, start, end, retstart, max(1, min(page, MAX_IDS - retstart))))
        res = data.get("esearchresult") if isinstance(data, dict) else None
        if not isinstance(res, dict) or not isinstance(res.get("idlist"), list) or "count" not in res:
            raise ParseError(f"esearch answer for {search.query!r} ({search.db}) has no id list or count")
        try:
            count = int(res["count"])
        except (TypeError, ValueError):
            raise ParseError(f"esearch count {res.get('count')!r} is not a number") from None
        if retstart == 0 and count > MAX_IDS:
            if start < end:
                mid = start + (end - start) // 2
                return (esearch_ids(ctx, search, start, mid, page)
                        + esearch_ids(ctx, search, mid + timedelta(days=1), end, page))
            log.warning("NCBI %s %r entered on %s: %d papers, only the first %d are read",
                        search.db, search.query, start, count, MAX_IDS)
        got = [str(x) for x in res["idlist"]]
        ids += got
        retstart += len(got)
        if not got or retstart >= min(count, MAX_IDS):
            return ids


def summaries(data: dict, ids: list[str]) -> dict[str, dict]:
    """The esummary records of ``ids``. A paper NCBI says it cannot give (or leaves out) is logged and skipped."""
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("uids"), list):
        raise ParseError("esummary answer has no result")
    out: dict[str, dict] = {}
    for uid in ids:
        rec = result.get(uid)
        if not isinstance(rec, dict) or rec.get("error"):
            log.warning("NCBI esummary gave no record for %s: %s", uid,
                        rec.get("error") if isinstance(rec, dict) else "left out")
            continue
        if str(rec.get("uid") or "").strip() != uid:
            raise ParseError(f"esummary record for {uid} carries uid {rec.get('uid')!r}")
        out[uid] = rec
    return out


def _esummary(ctx: FetchContext, db: str, ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for k in range(0, len(ids), SUMMARY_BATCH):
        chunk = ids[k:k + SUMMARY_BATCH]
        data = _get_json(ctx, f"{EUTILS}/esummary.fcgi?db={db}&retmode=json&id={','.join(chunk)}{_common()}")
        out.update(summaries(data, chunk))
    return out


# ───────────────────────────── papers ─────────────────────────────

def _article_ids(rec: dict | None) -> dict[str, str]:
    return {str(a.get("idtype")): str(a.get("value") or "") for a in (rec or {}).get("articleids") or []
            if isinstance(a, dict)}


def _pmc_id(value: str | None) -> str | None:
    """'PMC13643229', from 'PMC13643229', 'pmc-id: PMC13643229;' or a bare PMC uid."""
    v = (value or "").strip()
    if "PMC" in v:
        v = v[v.index("PMC") + 3:].split(";")[0].strip()
    return f"PMC{v}" if v.isdigit() and int(v) > 0 else None


def _pmid(value: str | None) -> str | None:
    v = (value or "").strip()
    return v if v.isdigit() and int(v) > 0 else None


_DOI = re.compile(r"(?<![0-9])(10\.[0-9]{4,9}/\S+)")


def clean_doi(value: str | None) -> str | None:
    """'10.1038/nature12373' from a DOI as records write it ('doi: 10.1038/…', 'https://doi.org/10.1038/…'), or
    None when it is not a DOI. The case is kept: DOIs ignore it."""
    m = _DOI.search(str(value or "").strip())
    return m.group(1).rstrip(".;,") if m else None


def doi_of(rec: dict | None) -> str | None:
    """A record's DOI: its ``articleids`` first, else its ``elocationid`` ('doi: 10.…'), which PubMed fills for
    papers ahead of print whose article ids do not carry it yet."""
    found = clean_doi(_article_ids(rec).get("doi"))
    if found:
        return found
    loc = str((rec or {}).get("elocationid") or "")
    return clean_doi(loc[loc.lower().index("doi:"):]) if "doi:" in loc.lower() else None


@dataclass
class Paper:
    pmid: str | None = None
    pmcid: str | None = None
    pubmed: dict | None = None            # its PubMed esummary record
    pmc: dict | None = None               # its PubMed Central esummary record
    kinds: dict[str, str] = field(default_factory=dict)          # search words → name | class
    dbs: dict[str, set[str]] = field(default_factory=dict)       # search words → databases that found it
    normal: bool = False                  # found by a window that is not a first look-back

    @property
    def external_id(self) -> str:
        return self.pmid or self.pmcid or ""

    def found(self, search: Search, normal: bool) -> None:
        self.kinds.setdefault(search.query, search.kind)
        self.dbs.setdefault(search.query, set()).add(search.db)
        self.normal = self.normal or normal

    def item(self) -> Item:
        rec = self.pubmed or self.pmc or {}
        found_in = sorted({db for dbs in self.dbs.values() for db in dbs})
        pubmed_url = PUBMED_URL.format(self.pmid) if self.pmid else None
        pmc_url = PMC_URL.format(self.pmcid) if self.pmcid else None
        url = pubmed_url if (pubmed_url and ("pubmed" in found_in or not pmc_url)) else pmc_url
        langs = (self.pubmed or {}).get("lang") or []
        authors = [a.get("name") for a in rec.get("authors") or [] if isinstance(a, dict)][:12]
        published = (parse_date(rec.get("sortpubdate") or rec.get("sortdate"))
                     or parse_date(rec.get("pubdate"), dayfirst=False))
        queries = sorted(self.kinds, key=str.casefold)
        title = (rec.get("title") or rec.get("vernaculartitle") or "").strip() or self.external_id
        pubtype = (self.pubmed or {}).get("pubtype")
        return Item(
            external_id=self.external_id,
            url=url or "",
            title=title,
            published=published,
            doc_type="literature",
            lang=LANGS.get(langs[0], langs[0][:2]) if langs else "en",
            structured={
                "pmid": self.pmid, "pmcid": self.pmcid, "pubmed_url": pubmed_url, "pmc_url": pmc_url,
                "query_term": queries,
                "queries": [{"query": q, "kind": self.kinds[q], "db": sorted(self.dbs[q])} for q in queries],
                "found_in": found_in,
                "class_only": all(k == "class" for k in self.kinds.values()),
                "look_back": not self.normal,
                "journal": rec.get("fulljournalname") or rec.get("source"),
                "pubdate": rec.get("pubdate"), "authors": authors,
                "pubtype": pubtype,
                "case_report": case_report(pubtype, title),
                "doi": doi_of(self.pubmed) or doi_of(self.pmc),
                "vernaculartitle": rec.get("vernaculartitle") or None,
            },
        )


def is_history(item: Item) -> bool:
    """Found only by a search's first look-back: stored as history, never alerted (the runner asks)."""
    return bool((item.structured or {}).get("look_back"))


def aliases(item: Item) -> list[str]:
    """Another id the same paper may be stored under: its PMC id, from before its PMID existed."""
    pmcid = (item.structured or {}).get("pmcid")
    return [pmcid] if pmcid and pmcid != item.external_id else []


def _known(db: str, uid: str, known: set[str]) -> bool:
    return (uid in known) if db == "pubmed" else (f"PMC{uid}" in known)


def _papers(records: dict[str, dict[str, dict]]) -> dict[tuple[str, str], Paper]:
    """(db, uid) → its paper: a PubMed record and the PMC record of the same paper become one."""
    of: dict[tuple[str, str], Paper] = {}
    by_pmid: dict[str, Paper] = {}
    by_pmcid: dict[str, Paper] = {}
    for uid, rec in records["pubmed"].items():
        p = Paper(pmid=uid, pmcid=_pmc_id(_article_ids(rec).get("pmc")), pubmed=rec)
        by_pmid[uid] = p
        if p.pmcid:
            by_pmcid[p.pmcid] = p
        of[("pubmed", uid)] = p
    for uid, rec in records["pmc"].items():
        ids = _article_ids(rec)
        pmcid = _pmc_id(ids.get("pmcid")) or _pmc_id(uid)
        pmid = _pmid(ids.get("pmid"))
        p = (by_pmid.get(pmid) if pmid else None) or by_pmcid.get(pmcid or "")
        if p is None:
            p = Paper(pmid=pmid, pmcid=pmcid)
            if pmid:
                by_pmid[pmid] = p
        p.pmc = rec
        p.pmcid = p.pmcid or pmcid
        p.pmid = p.pmid or pmid
        if p.pmcid:
            by_pmcid[p.pmcid] = p
        of[("pmc", uid)] = p
    return of


# ───────────────────────────── the run ─────────────────────────────

def _names_and_classes(ctx: FetchContext, source: SourceConfig) -> tuple[list[str], dict[str, list[str]]]:
    if source.options.get("terms"):
        return list(source.options["terms"]), {}
    store = getattr(ctx, "store", None)
    names = list(getattr(ctx, "watchlist", None) or [])
    if not names and store is not None:
        names = [r["inn_en"] for r in store.active_ingredients()]
    return names, (store.class_words("en") if store is not None else {})


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    opts = source.options
    today = date.today()
    _pace(ctx)
    store = getattr(ctx, "store", None)
    remembered = store is not None and not ctx.backfill
    names, classes = _names_and_classes(ctx, source)
    state = store.literature_searches() if remembered else {}
    known = store.literature_known_ids(source.id) if store is not None else set()
    other = Elsewhere.load(store, source.id)       # the papers Europe PMC stored first
    page = int(opts.get("page_size", PAGE_SIZE))

    runs: list[dict[str, Any]] = []
    hits: dict[tuple[str, str], list[tuple[Search, bool]]] = {}      # (db, uid) → (search, normal)
    for s in searches(names, classes):
        windows, row = plan(ctx, s, state.get(s.key), opts, today, remembered)
        uids: set[str] = set()
        for w in windows:
            for uid in esearch_ids(ctx, s, w.start, w.end, page):
                uids.add(uid)
                hits.setdefault((s.db, uid), []).append((s, not w.history))
        runs.append({"search": s, "row": row, "uids": uids})

    def elsewhere(key: tuple[str, str]) -> str | None:
        """The document of the paper another literature source stored under this PMID or PMC id."""
        if _known(key[0], key[1], known):
            return None
        return other.find(pmid=key[1]) if key[0] == "pubmed" else other.find(pmcid=f"PMC{key[1]}")

    # A paper another source stored first is never read: it records that NCBI found it too.
    for key, found in hits.items():
        doc = elsewhere(key)
        for s, _ in found if doc else []:
            other.found(doc, s.db, s.query, s.kind)

    # Read the papers new to PHAROS: new ones first, then a look-back's name papers, then its class papers.
    def rank(key: tuple[str, str]) -> tuple:
        normal = any(n for _, n in hits[key])
        named = any(s.kind == "name" for s, _ in hits[key])
        return (not normal, not named, DBS.index(key[0]), -int(key[1]) if key[1].isdigit() else 0)

    wanted = sorted((k for k in hits if not _known(k[0], k[1], known) and not elsewhere(k)), key=rank)
    if not ctx.backfill:
        cap = int(opts.get("max_new_items", MAX_NEW_ITEMS))
        # New papers over the cap wait for the next run, which must read their days again: the runner then
        # leaves last_ok_at alone. A look-back's own papers over the cap need not: it stays unfinished.
        ctx.held_back = sum(1 for k in wanted[cap:] if any(n for _, n in hits[k]))
        wanted = wanted[:cap]
    records = {db: _esummary(ctx, db, [uid for d, uid in wanted if d == db]) for db in DBS}
    asked = set(wanted)
    # The publication types of a paper PMC alone found are in its PubMed record: read those too.
    pmc_only = list(dict.fromkeys(
        pmid for pmid in (_pmid(_article_ids(rec).get("pmid")) for rec in records["pmc"].values())
        if pmid and pmid not in records["pubmed"]))
    if pmc_only:
        records["pubmed"].update(_esummary(ctx, "pubmed", pmc_only))

    paper_of = _papers(records)
    for key, found in hits.items():
        if key in paper_of:
            for s, normal in found:
                paper_of[key].found(s, normal)
    items: dict[int, Item] = {}
    dropped: set[int] = set()       # stored first by another source under an id only the record gave (or a DOI)
    for p in paper_of.values():
        if id(p) in items or id(p) in dropped or not p.external_id:
            continue
        it = p.item()
        doc = other.find(p.pmid, p.pmcid, it.structured.get("doi"))
        if doc:
            dropped.add(id(p))
            for q, dbs in p.dbs.items():
                for db in dbs:
                    other.found(doc, db, q, p.kinds[q])
            continue
        items[id(p)] = it
    again = other.save(store)
    if again:
        log.info("NCBI found %d paper(s) already stored from another literature source", again)

    # What each search found, for after_store: a uid is settled when it was stored before (by this source or
    # another), or NCBI gave no record of it; otherwise it waits for its paper to be stored.
    for run in runs:
        s = run["search"]
        wait: list[tuple[str, list[str]]] = []
        for uid in run.pop("uids"):
            key = (s.db, uid)
            if _known(s.db, uid, known) or elsewhere(key) or (key in paper_of and id(paper_of[key]) in dropped):
                continue
            if key in paper_of:
                it = items[id(paper_of[key])]
                wait.append((it.external_id, aliases(it)))
            elif key not in asked:
                wait.append(("", []))                     # not read this run: never settled
        run["wait"] = wait
    ctx.literature_runs = runs if remembered else None

    out = list(items.values())
    out.sort(key=lambda it: (is_history(it), bool(it.structured["class_only"]),
                             -(it.published or date.min).toordinal(), it.external_id))
    return out


def after_store(ctx: FetchContext, source: SourceConfig, items: list[Item], stored: set[str]) -> None:
    """Remember every search this run made; a look-back is done once every paper it found is stored."""
    runs = getattr(ctx, "literature_runs", None)
    store = getattr(ctx, "store", None)
    ctx.literature_runs = None
    if not runs or store is None:
        return
    rows = []
    for run in runs:
        s, row = run["search"], run["row"]
        done = row["done"] or all(eid and (eid in stored or any(a in stored for a in al))
                                  for eid, al in run["wait"])
        rows.append({"db": s.db, "query": s.key[1], "kind": s.kind, "look_back_from": row["look_back_from"],
                     "history_until": row["history_until"], "done": done})
    store.save_literature_searches(rows)
