"""PubMed literature watch (NCBI E-utilities), weekly: one search per active ingredient.

esearch (``db=pubmed``, by Entrez date) then esummary for the ids found. Only metadata and the
PubMed link are stored (doc_type 'literature'); abstracts and full texts are not fetched.
``NCBI_API_KEY`` is sent when present (10 requests/s instead of 3; the context waits 1 s anyway).

Options:
  terms          list  search terms instead of the active ingredients (tests, one-off searches)
  lookback_days  int   default 10 (a weekly run with overlap); after a missed week the search
                       starts at the last complete run instead (3 days' overlap, at most 90 days back)
  field          str   search field tag, default "tiab" (title/abstract)
  retmax         int   default 200 per search

The ingredient searched for is stored in ``structured.query_term`` and matched as a structured
field, so a paper found for lornoxicam is linked to lornoxicam even when the title only names it
in a translation.

E-utilities answers HTTP 500/502/504 in bursts (on 2026-11-05 most esearch calls, from any network,
while esummary answered), so each call is retried after 5, 15, 30 and 60 s before the source fails.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from urllib.parse import quote

from collectors.parsers.base import FetchContext, FetchError, Item, ParseError, SourceConfig, parse_date

log = logging.getLogger(__name__)

STRUCTURED_FIELDS = ["query_term"]

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
LANGS = {"eng": "en", "ger": "de", "fre": "fr", "ita": "it", "spa": "es", "por": "pt", "dut": "nl",
         "dan": "da", "swe": "sv", "nor": "nb", "fin": "fi", "ice": "is", "jpn": "ja", "kor": "ko",
         "ara": "ar", "chi": "zh", "rus": "ru", "pol": "pl", "tur": "tr"}
NCBI_RETRY_WAITS_S = (5.0, 15.0, 30.0, 60.0)
NCBI_FLAKY = (500, 502, 504)
OVERLAP_DAYS = 3
MAX_CATCH_UP_DAYS = 90


def _common() -> str:
    key = os.environ.get("NCBI_API_KEY")
    return "&tool=pharos" + (f"&api_key={key}" if key else "")


def _get_json(ctx: FetchContext, url: str) -> dict:
    """``url`` as JSON, waiting out E-utilities' passing server errors."""
    for wait in (*NCBI_RETRY_WAITS_S, None):
        try:
            return ctx.get(url, accept="application/json").json()
        except FetchError as exc:
            if wait is None or exc.status not in NCBI_FLAKY:
                raise
            log.info("NCBI HTTP %s: waiting %.0f s, then retrying", exc.status, wait)
            ctx._sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


def _start(ctx: FetchContext, opts: dict, today: date) -> date:
    """The first Entrez date searched: the lookback, or the last complete run when that is older."""
    if ctx.backfill:
        return today - timedelta(days=31 * int(getattr(ctx, "backfill_months", 12) or 12))
    start = today - timedelta(days=int(opts.get("lookback_days", 10)))
    last_ok = getattr(ctx, "last_ok_at", None)
    if last_ok is not None:
        start = min(start, last_ok.date() - timedelta(days=OVERLAP_DAYS))
    return max(start, today - timedelta(days=MAX_CATCH_UP_DAYS))


def _terms(ctx: FetchContext, source: SourceConfig) -> list[str]:
    if source.options.get("terms"):
        return list(source.options["terms"])
    if getattr(ctx, "watchlist", None):
        return list(ctx.watchlist)
    if ctx.db is None:
        return []
    rows = ctx.db.fetchall("select inn_en from ingredient where active order by inn_en")
    return [r["inn_en"] for r in rows]


def summary_to_item(doc: dict, term: str) -> Item:
    pmid = str(doc.get("uid") or "").strip()
    if not pmid:
        raise ParseError("esummary record without uid")
    langs = doc.get("lang") or []
    doi = next((a.get("value") for a in doc.get("articleids") or [] if a.get("idtype") == "doi"),
               None)
    return Item(
        external_id=pmid,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        title=(doc.get("title") or doc.get("vernaculartitle") or "").strip() or f"PMID {pmid}",
        published=parse_date(doc.get("sortpubdate")) or parse_date(doc.get("pubdate"),
                                                                    dayfirst=False),
        doc_type="literature",
        lang=LANGS.get(langs[0], langs[0][:2]) if langs else "en",
        structured={
            "pmid": pmid, "query_term": term, "journal": doc.get("fulljournalname") or doc.get("source"),
            "pubdate": doc.get("pubdate"), "authors": [a.get("name") for a in doc.get("authors") or []][:12],
            "pubtype": doc.get("pubtype"), "doi": doi, "vernaculartitle": doc.get("vernaculartitle"),
        },
    )


def parse_esummary(data: dict, term: str) -> list[Item]:
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise ParseError("esummary response has no result")
    return [summary_to_item(result[uid], term) for uid in result.get("uids") or [] if uid in result]


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    opts = source.options
    today = date.today()
    start = _start(ctx, opts, today)
    field = opts.get("field", "tiab")
    retmax = int(opts.get("retmax", 200))
    items: dict[str, Item] = {}
    for term in _terms(ctx, source):
        q = quote(f'"{term}"[{field}]')
        url = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&datetype=edat&retmax={retmax}"
               f"&mindate={start:%Y/%m/%d}&maxdate={today:%Y/%m/%d}&term={q}{_common()}")
        data = _get_json(ctx, url)
        ids = ((data.get("esearchresult") or {}).get("idlist")) if isinstance(data, dict) else None
        if ids is None:
            raise ParseError("esearch response has no idlist")
        for k in range(0, len(ids), 100):
            chunk = ",".join(ids[k:k + 100])
            summ = _get_json(ctx, f"{EUTILS}/esummary.fcgi?db=pubmed&retmode=json&id={chunk}{_common()}")
            for item in parse_esummary(summ, term):
                items.setdefault(item.external_id, item)
    return list(items.values())
