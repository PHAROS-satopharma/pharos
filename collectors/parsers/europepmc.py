"""Europe PMC literature watch (EMBL-EBI's REST API, no key): the words NCBI's watch searches, daily, adding what
PubMed misses: preprints, and papers that name a word only inside their open full text.

Searches. Every word the NCBI watch searches (``pubmed.searches``: each active ingredient's English INN, then the
English words of the drug classes it searches in the literature) is searched once here, as a phrase, among journal
articles and preprints, by the day Europe PMC first indexed the record (its Entrez date):

    "<words>" AND (SRC:MED OR SRC:PMC OR SRC:PPR) AND FIRST_IDATE:[<start> TO <end>]

SRC:MED is PubMed's records, SRC:PMC full texts with no PubMed record, SRC:PPR preprints (medRxiv, bioRxiv,
Research Square, Preprints.org, SSRN …). Europe PMC searches inside the open full texts it holds as well as titles
and abstracts. Patents, theses, Agricola, Chinese Biological Abstracts and NHS guidelines are left out. The words are
quoted, with ``synonym=false``: Europe PMC reads a bracket or a colon in bare words as query syntax and silently
drops what it cannot parse (on 6 Nov 2026 an unclosed date range was ignored and 18,552 papers came back instead of
56), and a quoted phrase is the words exactly as written.

Two steps, as the NCBI watch. Every search is read with ``resultType=idlist`` (ids only, 1,000 a page, under a
second a page). Paging is by cursor: ``cursorMark=*``, then each answer's ``nextCursorMark``, until an answer has no
``nextCursorMark`` or no result; ``hitCount`` counts a PubMed record and its full text apart where the page lists
them once (56 counted, 53 listed), so it never ends the paging. Only the papers new to PHAROS are then read with
``resultType=lite``, 100 at a time, by a query naming them: ``(SRC:MED AND EXT_ID:42968865) OR …``. At most
``max_new_items`` are read per run; new papers over that cap make the run incomplete (``ctx.held_back``), as NCBI's.

One paper, one document (``collectors/parsers/_literature.py``). A hit with the PMID or PMC id of a paper the NCBI
watch stored is not read again: that paper records that Europe PMC found it ('europepmc' in ``structured.found_in``
and in the databases of its search words). The same holds for a paper whose record carries the DOI of a stored
paper. A paper new to PHAROS is stored under its PMID, else its PMC id, else its Europe PMC id (``PPR…`` for a
preprint), with the NCBI watch's structured fields (pmid, pmcid, doi, pubmed_url, pmc_url, query_term, queries,
found_in ``["europepmc"]``, class_only, look_back, journal, pubdate, authors, pubtype, case_report) and its own:
``europepmc_id``, ``europepmc_url`` (its page, also the item's link) and ``preprint`` (true for SRC:PPR: the
Ingredients screen says "Preprint, not peer reviewed"). A preprint's ``journal`` is its server ("Research Square").
``case_report`` is ``{"reason": "pubtype"}`` when Europe PMC types it "case reports" (PubMed's type), else the title
rule of ``pubmed.case_report``. The lite record gives no language: a paper is stored as English.

Windows: exactly the NCBI watch's (``pubmed.plan``: the last complete run less 3 days, a search's own last search
when earlier, a new word's 12-month look-back stored as history, a look-back cut short continued). Each search is
remembered in ``literature_search`` under the database 'europepmc' (migration 0066).

Time. The searches stop starting after ``search_budget_min`` minutes (a look-back of a common word reads tens of
thousands of ids): the searches already done before go first, then the look-backs, names before class words. A
search not run this time keeps its row as it was, so the next run reaches back to its own last search (its days
are read then) or continues its look-back. The runner's ``time_budget_min`` then bounds storing the papers.

Etiquette: a User-Agent naming PHAROS and its pharos@satopharma.com mailbox, as Europe PMC asks of programs (in a
header, never in the address, so no log line carries it), and at most two requests a second. Server errors are
retried by the fetch layer, 429 and 503 waited out; an answer without its result list raises ParseError.

Options:
  terms                  list  words to search instead of the active ingredients (tests, one-off searches)
  lookback_days          int   default 10: the window before the source's first complete run
  look_back_months       int   default 12: a new search's look-back
  class_look_back_months int   default look_back_months: a new class word's look-back
  page_size              int   default 1000 ids per page (Europe PMC's most)
  max_new_items          int   papers read and stored per normal run (the runner caps it too)
  search_budget_min      float default 6: minutes of searching per run
"""

from __future__ import annotations

import dataclasses
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator
from urllib.parse import urlencode

from collectors.parsers import pubmed
from collectors.parsers._literature import Elsewhere
from collectors.parsers.base import FetchContext, Item, ParseError, SourceConfig, parse_date
from collectors.parsers.pubmed import Search, after_store, aliases, is_history, plan

__all__ = ["after_store", "aliases", "is_history", "list_items"]

log = logging.getLogger(__name__)

STRUCTURED_FIELDS = ["query_term"]

REST = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
HOST = "www.ebi.ac.uk"
ARTICLE_URL = "https://europepmc.org/article/{}/{}"
DB = "europepmc"
SOURCES = "(SRC:MED OR SRC:PMC OR SRC:PPR)"
USER_AGENT = "PHAROS pharmacovigilance literature watch (pharos@satopharma.com)"
PAGE_SIZE = 1_000             # the most Europe PMC serves in one page
RECORD_BATCH = 100            # papers read by one lite query
MAX_PAGES = 500               # a cursor that never ends stops here (500,000 ids)
MAX_NEW_ITEMS = 400           # the runner's default
SEARCH_BUDGET_MIN = 6.0
GAP_S = 0.5                   # two requests a second
CASE_REPORT_TYPES = frozenset({"case reports", "case-report"})
_ID = re.compile(r"^[A-Za-z0-9]{1,40}$")
_SRC = re.compile(r"^[A-Z]{3}$")
_TAG = re.compile(r"</?(?:i|b|u|em|strong|sup|sub|sc|span)\b[^>]*>", re.IGNORECASE)
_clock = time.monotonic       # replaced by tests


def _pace(ctx: FetchContext) -> None:
    if ctx.host_gap_s > GAP_S:
        ctx._host_gap.setdefault(HOST, GAP_S)


def searches(names: list[str], class_words: dict[str, list[str]]) -> list[Search]:
    """The NCBI watch's words, in its order, each once."""
    return [dataclasses.replace(s, db=DB) for s in pubmed.searches(names, class_words) if s.db == "pubmed"]


def phrase(words: str) -> str:
    """``words`` as one quoted phrase (a quote or a backslash inside escaped)."""
    return '"' + words.replace("\\", "\\\\").replace('"', '\\"') + '"'


def query(search: Search, start: date, end: date) -> str:
    return f"{phrase(search.query)} AND {SOURCES} AND FIRST_IDATE:[{start:%Y-%m-%d} TO {end:%Y-%m-%d}]"


def _get(ctx: FetchContext, params: dict[str, Any]) -> dict:
    url = f"{REST}?{urlencode({**params, 'synonym': 'false', 'format': 'json'})}"
    data = ctx.get(url, accept="application/json", headers={"User-Agent": USER_AGENT}).json()
    rows = (data.get("resultList") or {}).get("result") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError("Europe PMC answer has no result list")
    return data


def pages(ctx: FetchContext, q: str, result_type: str, page: int = PAGE_SIZE) -> Iterator[list[dict]]:
    """Each page of results of ``q``, cursor by cursor."""
    cursor = "*"
    for _ in range(MAX_PAGES):
        data = _get(ctx, {"query": q, "resultType": result_type, "pageSize": max(1, min(page, PAGE_SIZE)),
                          "cursorMark": cursor})
        rows = [r for r in data["resultList"]["result"] if isinstance(r, dict)]
        if rows:
            yield rows
        nxt = data.get("nextCursorMark")
        if not rows or not nxt or str(nxt) == cursor:
            return
        cursor = str(nxt)
    log.warning("Europe PMC: paging stopped after %d pages", MAX_PAGES)


# ───────────────────────────── hits ─────────────────────────────

@dataclass(frozen=True)
class Hit:
    src: str                  # MED | PMC | PPR
    id: str                   # Europe PMC's id: the PMID for MED, PMC… or PPR…
    pmid: str | None = None
    pmcid: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.src, self.id)


def hit(rec: dict) -> Hit | None:
    """The ids of one search result; None for one that cannot be asked for again."""
    src, rid = str(rec.get("source") or "").strip(), str(rec.get("id") or "").strip()
    if not _SRC.match(src) or not _ID.match(rid):
        log.warning("Europe PMC result without a usable id skipped (source %r)", src[:10])
        return None
    return Hit(src, rid, pubmed._pmid(rec.get("pmid")), pubmed._pmc_id(rec.get("pmcid")))


def search_hits(ctx: FetchContext, search: Search, start: date, end: date, page: int = PAGE_SIZE) -> list[Hit]:
    """Every paper ``search`` finds among the records first indexed ``start``…``end`` (both included)."""
    out: list[Hit] = []
    for rows in pages(ctx, query(search, start, end), "idlist", page):
        out += [h for h in map(hit, rows) if h is not None]
    return out


def records(ctx: FetchContext, hits: list[Hit]) -> dict[tuple[str, str], dict]:
    """The lite record of each hit. A paper Europe PMC does not give back is logged and left out."""
    out: dict[tuple[str, str], dict] = {}
    for k in range(0, len(hits), RECORD_BATCH):
        chunk = hits[k:k + RECORD_BATCH]
        asked = {h.key for h in chunk}
        q = " OR ".join(f"(SRC:{h.src} AND EXT_ID:{h.id})" for h in chunk)
        for rows in pages(ctx, q, "lite"):
            for r in rows:
                key = (str(r.get("source") or ""), str(r.get("id") or ""))
                if key in asked:
                    out[key] = r
        for key in sorted(asked - set(out)):
            log.warning("Europe PMC gave no record for %s/%s", *key)
    return out


def abstract(ctx: FetchContext, europepmc_id: str) -> str:
    """The title and abstract of one paper, from its Europe PMC record (``resultType=core``), a paragraph per line:
    what a case opened from a preprint is read from (``collectors/cases/paper.py``)."""
    if not _ID.match(europepmc_id or ""):
        raise ParseError(f"not a Europe PMC id: {europepmc_id[:40]!r}")
    src = "PPR" if europepmc_id.startswith("PPR") else "PMC" if europepmc_id.startswith("PMC") else "MED"
    data = _get(ctx, {"query": f"EXT_ID:{europepmc_id} AND SRC:{src}", "resultType": "core", "pageSize": 1})
    rows = [r for r in data["resultList"]["result"] if isinstance(r, dict) and r.get("id") == europepmc_id]
    if not rows:
        return ""
    rec = rows[0]
    paragraphs = re.split(r"<(?:/p|/title|/h\d|br\s*/?)>", str(rec.get("abstractText") or ""), flags=re.IGNORECASE)
    lines = [_text(rec.get("title"))] + [" ".join(re.sub(r"<[^>]+>", " ", p).split()) for p in paragraphs]
    return "\n".join(x for x in lines if x)


# ───────────────────────────── papers ─────────────────────────────

def _text(value: Any) -> str:
    return " ".join(_TAG.sub("", str(value or "")).split())


def _case_report(pubtype: list[str], title: str) -> dict | None:
    typed = any(t.casefold() in CASE_REPORT_TYPES for t in pubtype)
    return pubmed.case_report([pubmed.CASE_REPORT_TYPE] if typed else [], title)


@dataclass
class Paper:
    hit: Hit
    rec: dict | None = None
    kinds: dict[str, str] = field(default_factory=dict)          # search words → name | class
    normal: bool = False                  # found by a window that is not a first look-back

    def found(self, search: Search, normal: bool) -> None:
        self.kinds.setdefault(search.query, search.kind)
        self.normal = self.normal or normal

    def item(self) -> Item:
        rec = self.rec or {}
        pmid = pubmed._pmid(rec.get("pmid")) or self.hit.pmid
        pmcid = pubmed._pmc_id(rec.get("pmcid")) or self.hit.pmcid
        external_id = pmid or pmcid or self.hit.id
        pubtype = [t.strip() for t in str(rec.get("pubType") or "").split(";") if t.strip()]
        preprint = self.hit.src == "PPR" or any(t.casefold() == "preprint" for t in pubtype)
        title = _text(rec.get("title")) or external_id
        url = ARTICLE_URL.format(self.hit.src, self.hit.id)
        authors = [a.strip() for a in _text(rec.get("authorString")).rstrip(".").split(",") if a.strip()][:12]
        queries = sorted(self.kinds, key=str.casefold)
        return Item(
            external_id=external_id,
            url=url,
            title=title,
            published=parse_date(rec.get("firstPublicationDate")),
            doc_type="literature",
            lang="en",
            structured={
                "pmid": pmid, "pmcid": pmcid,
                "pubmed_url": pubmed.PUBMED_URL.format(pmid) if pmid else None,
                "pmc_url": pubmed.PMC_URL.format(pmcid) if pmcid else None,
                "europepmc_id": self.hit.id, "europepmc_url": url, "preprint": preprint,
                "query_term": queries,
                "queries": [{"query": q, "kind": self.kinds[q], "db": [DB]} for q in queries],
                "found_in": [DB],
                "class_only": all(k == "class" for k in self.kinds.values()),
                "look_back": not self.normal,
                "journal": (_text(rec.get("journalTitle"))
                            or _text((rec.get("bookOrReportDetails") or {}).get("publisher")) or None),
                "pubdate": rec.get("firstPublicationDate"), "authors": authors,
                "pubtype": pubtype,
                "case_report": _case_report(pubtype, title),
                "doi": str(rec.get("doi") or "").strip() or None,
                "vernaculartitle": None,
            },
        )


# ───────────────────────────── the run ─────────────────────────────

def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    opts = source.options
    today = date.today()
    _pace(ctx)
    store = getattr(ctx, "store", None)
    remembered = store is not None and not ctx.backfill
    names, classes = pubmed._names_and_classes(ctx, source)
    state = store.literature_searches() if remembered else {}
    known = store.literature_known_ids(source.id) if store is not None else set()
    other = Elsewhere.load(store, source.id)
    page = int(opts.get("page_size", PAGE_SIZE))
    budget_s = float(opts.get("search_budget_min", SEARCH_BUDGET_MIN)) * 60

    planned = [(s, *plan(ctx, s, state.get(s.key), opts, today, remembered)) for s in searches(names, classes)]
    # the searches done before (a few days each) first, then the look-backs; sorted() keeps names before classes
    planned.sort(key=lambda p: any(w.history for w in p[1]))
    started = _clock()
    runs: list[dict[str, Any]] = []
    hits: dict[tuple[str, str], list[tuple[Search, bool]]] = {}      # (src, id) → (search, normal)
    hit_of: dict[tuple[str, str], Hit] = {}
    for n, (s, windows, row) in enumerate(planned):
        if not ctx.backfill and _clock() - started >= budget_s:
            log.warning("Europe PMC: %.0f minutes of searching reached, %d of %d searches wait for the next run",
                        budget_s / 60, len(planned) - n, len(planned))
            break
        keys: set[tuple[str, str]] = set()
        for w in windows:
            for h in search_hits(ctx, s, w.start, w.end, page):
                keys.add(h.key)
                hit_of.setdefault(h.key, h)
                hits.setdefault(h.key, []).append((s, not w.history))
        runs.append({"search": s, "row": row, "keys": keys})

    def mine(h: Hit) -> bool:
        return any(x in known for x in (h.id, h.pmid, h.pmcid) if x)

    # Papers another source stored: found again, never read.
    settled: set[tuple[str, str]] = set()
    for key, found in hits.items():
        h = hit_of[key]
        doc = None if mine(h) else other.find(h.pmid, h.pmcid)
        if mine(h) or doc:
            settled.add(key)
        if doc:
            for s, _ in found:
                other.found(doc, DB, s.query, s.kind)

    # Read the papers new to PHAROS: new ones first, then a look-back's name papers, then its class papers.
    order = {k: n for n, k in enumerate(hits)}

    def rank(key: tuple[str, str]) -> tuple:
        normal = any(n for _, n in hits[key])
        named = any(s.kind == "name" for s, _ in hits[key])
        return (not normal, not named, order[key])

    wanted = sorted((k for k in hits if k not in settled), key=rank)
    if not ctx.backfill:
        cap = int(opts.get("max_new_items", MAX_NEW_ITEMS))
        ctx.held_back = sum(1 for k in wanted[cap:] if any(n for _, n in hits[k]))
        wanted = wanted[:cap]
    recs = records(ctx, [hit_of[k] for k in wanted])
    asked = set(wanted)

    papers: dict[tuple[str, str], Paper] = {}
    for key in wanted:
        rec = recs.get(key)
        if rec is None:
            settled.add(key)                     # Europe PMC gave no record: nothing to wait for
            continue
        h = hit_of[key]
        doc = other.find(pubmed._pmid(rec.get("pmid")) or h.pmid, pubmed._pmc_id(rec.get("pmcid")) or h.pmcid,
                         rec.get("doi"))
        if doc:                                  # the same DOI as a paper another source stored
            settled.add(key)
            for s, _ in hits[key]:
                other.found(doc, DB, s.query, s.kind)
            continue
        p = Paper(h, rec)
        for s, normal in hits[key]:
            p.found(s, normal)
        papers[key] = p
    items = {key: p.item() for key, p in papers.items()}
    again = other.save(store)
    if again:
        log.info("Europe PMC found %d paper(s) already stored from another literature source", again)

    # What each search found, for after_store: a paper is settled when it was stored before (here or by another
    # source) or Europe PMC gave no record of it; otherwise it waits for its paper to be stored.
    for run in runs:
        wait: list[tuple[str, list[str]]] = []
        for key in run.pop("keys"):
            if key in settled:
                continue
            if key in items:
                wait.append((items[key].external_id, aliases(items[key])))
            elif key not in asked:
                wait.append(("", []))                     # not read this run: never settled
        run["wait"] = wait
    ctx.literature_runs = runs if remembered else None

    out = list(items.values())
    out.sort(key=lambda it: (is_history(it), bool(it.structured["class_only"]),
                             -(it.published or date.min).toordinal(), it.external_id))
    return out
