"""Legal open-access full text of the literature papers, found by Unpaywall (migration 0070, validation row 22).

    python -m collectors.fulltext [--limit N]     the daily step after Coding (collect.yml)

1. DOIs. A paper's DOI comes with its PubMed record (``structured.doi``: its article ids, else its elocation id,
   ``collectors/parsers/pubmed.py``). A paper of the last year with a PMID and no DOI is asked again in PubMed
   (esummary, 200 papers a request, ``NCBI_API_KEY`` when set) at most every 30 days (``structured.doi_checked``):
   a paper ahead of print often gets its DOI later.
2. Unpaywall. Each literature paper of the last year with a DOI is looked up at
   ``https://api.unpaywall.org/v2/{doi}?email=pharos@satopharma.com`` (no key; Unpaywall allows 100,000 calls a
   day, PHAROS makes at most ``LIMIT`` a run, about four a second) and ``structured.oa`` keeps what it says:
   ``is_oa``; the best open location's ``url``, ``pdf_url``, ``license``, ``version`` (published, accepted or
   submitted) and ``host_type`` (publisher or repository); ``oa_status``; ``pdfs``, the open PDFs to try for a
   case (the best first, then repositories, published before accepted before submitted, each with its own
   licence); and ``checked``, when it was asked. A DOI Unpaywall does not know is kept as ``known`` false. A
   paper with no open copy is asked again after 30 days; an open one is not asked again. One failure (a timeout,
   a server error) never stops the batch: that paper waits for the next run; 20 failures in a row end the run.
3. Cases. ``fetch_open_pdf`` is how a case opened from a paper (``collectors/cases/paper.py``) fetches the open
   PDF when PubMed Central holds no full text: only through ``FetchContext(public_only=True)`` (every host and
   every redirect checked to be on the public internet, the connection pinned to the checked address), at most
   ``MAX_PDF_BYTES``, and only an answer whose declared type is a PDF and whose bytes start ``%PDF-``.

The run logs are public (the repository is): they carry counts and exception names only, never a title or a DOI.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from collectors.parsers.pubmed import EUTILS, clean_doi, doi_of, summaries

log = logging.getLogger("collectors.fulltext")

UNPAYWALL = "https://api.unpaywall.org/v2/"
EMAIL = "pharos@satopharma.com"
USER_AGENT = f"PHAROS pharmacovigilance monitor (Sato Pharma; mailto:{EMAIL})"
RECHECK_DAYS = 30
MAX_AGE_DAYS = 365
LIMIT = 2000             # Unpaywall lookups a run; what is left waits for the next day
DOI_LIMIT = 4000         # papers asked for their DOI a run
DOI_BATCH = 200
GAP_S = 0.25             # between two Unpaywall calls
TIME_BUDGET_S = 11 * 60  # the step's timeout is 15 minutes
MAX_FAILURES_IN_A_ROW = 20
MAX_PDFS = 4
MAX_PDF_BYTES = 20 * 1024 * 1024   # base64 in the reader's request stays under its 32 MB
VERSIONS = {"publishedVersion": "published", "acceptedVersion": "accepted", "submittedVersion": "submitted"}
_VERSION_ORDER = {"published": 0, "accepted": 1, "submitted": 2}
HOST_TYPES = ("publisher", "repository")
PDF_TYPES = ("application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream")

DOI_PENDING_SQL = """
select d.id::text as id, d.structured ->> 'pmid' as pmid
  from document d
 where d.doc_type = 'literature'
   and coalesce(d.structured ->> 'pmid', '') ~ '^[0-9]+$'
   and coalesce(d.structured ->> 'doi', '') = ''
   and d.first_seen_at >= now() - make_interval(days => %(age)s)
   and coalesce((d.structured ->> 'doi_checked')::timestamptz, '-infinity'::timestamptz)
       < now() - make_interval(days => %(recheck)s)
 order by d.first_seen_at desc
 limit %(limit)s
"""

DOI_STORE_SQL = """
update document
   set structured = coalesce(structured, '{}'::jsonb)
                    || jsonb_build_object('doi_checked', now())
                    || case when %(doi)s::text is null then '{}'::jsonb
                            else jsonb_build_object('doi', %(doi)s::text) end
 where id = %(id)s::uuid
"""

PENDING_SQL = """
select d.id::text as id, d.structured ->> 'doi' as doi
  from document d
 where d.doc_type = 'literature'
   and coalesce(d.structured ->> 'doi', '') like '10.%%'
   and d.first_seen_at >= now() - make_interval(days => %(age)s)
   and (jsonb_typeof(d.structured -> 'oa') is distinct from 'object'
        or (coalesce(d.structured -> 'oa' ->> 'is_oa', '') <> 'true'
            and coalesce((d.structured -> 'oa' ->> 'checked')::timestamptz, '-infinity'::timestamptz)
                < now() - make_interval(days => %(recheck)s)))
 order by d.first_seen_at desc
 limit %(limit)s
"""

STORE_SQL = """
update document
   set structured = coalesce(structured, '{}'::jsonb)
                    || jsonb_build_object('oa', %(oa)s::jsonb || jsonb_build_object('checked', now()))
 where id = %(id)s::uuid
"""


# ───────────────────────────── what Unpaywall says ─────────────────────────────

def _http(url: Any) -> str | None:
    """An absolute http(s) address, else None (a page only ever links to these)."""
    u = str(url or "").strip()
    parts = urlsplit(u) if u else None
    if not parts or parts.scheme.lower() not in ("http", "https") or not parts.hostname or len(u) > 2000:
        return None
    return u


def _word(value: Any, n: int = 100) -> str | None:
    text = " ".join(str(value or "").split())[:n]
    return text or None


def _location(loc: dict) -> dict:
    host = loc.get("host_type")
    return {"url": _http(loc.get("url")) or _http(loc.get("url_for_landing_page")) or _http(loc.get("url_for_pdf")),
            "pdf_url": _http(loc.get("url_for_pdf")),
            "license": _word(loc.get("license")),
            "version": VERSIONS.get(str(loc.get("version") or "")),
            "host_type": host if host in HOST_TYPES else None}


def open_access(data: dict | None) -> dict:
    """``structured.oa`` from an Unpaywall answer (None: the DOI is not in Unpaywall). ``checked`` is the database's."""
    if not isinstance(data, dict):
        return {"is_oa": False, "known": False}
    best = data.get("best_oa_location") if isinstance(data.get("best_oa_location"), dict) else None
    locs = [x for x in data.get("oa_locations") or [] if isinstance(x, dict)]
    status = _word(data.get("oa_status"), 20)
    first = _location(best) if best else None
    if not (data.get("is_oa") and first and first["url"]):
        return {"is_oa": False, "known": True, "oa_status": status}
    rest = sorted((_location(x) for x in locs if x is not best),
                  key=lambda x: (x["host_type"] != "repository", _VERSION_ORDER.get(x["version"] or "", 3)))
    pdfs: list[dict] = []
    for loc in [first, *rest]:
        if loc["pdf_url"] and all(p["pdf_url"] != loc["pdf_url"] for p in pdfs):
            pdfs.append({k: loc[k] for k in ("pdf_url", "license", "version", "host_type")})
    return {"is_oa": True, "known": True, "oa_status": status, **first, "pdfs": pdfs[:MAX_PDFS]}


def due(oa: Any, now: datetime | None = None) -> bool:
    """Whether a paper is asked (again): never asked, or no open copy found and asked 30 days ago or more. The
    same rule as ``PENDING_SQL``."""
    if not isinstance(oa, dict):
        return True
    if oa.get("is_oa") is True:
        return False
    try:
        checked = datetime.fromisoformat(str(oa.get("checked")).replace("Z", "+00:00"))
    except ValueError:
        return True
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return checked < (now or datetime.now(timezone.utc)) - timedelta(days=RECHECK_DAYS)


def unpaywall_url(doi: str) -> str:
    return f"{UNPAYWALL}{quote(doi, safe='/():;')}?email={EMAIL}"


def make_ask(get: Callable[[str], tuple[int, bytes]]) -> Callable[[str], dict | None]:
    """``ask(doi)``: Unpaywall's answer as JSON, or None when it does not know the DOI (404, 422). Anything else
    raises: the paper is asked again on the next run."""

    def ask(doi: str) -> dict | None:
        status, body = get(unpaywall_url(doi))
        if status in (404, 422):
            return None
        if status != 200:
            raise RuntimeError(f"Unpaywall answered HTTP {status}")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError("Unpaywall's answer is not an object")
        return data

    return ask


def _client_get(client: Any) -> Callable[[str], tuple[int, bytes]]:
    def get(url: str) -> tuple[int, bytes]:
        time.sleep(GAP_S)
        res = client.get(url)
        return res.status_code, res.content

    return get


# ───────────────────────────── the daily run ─────────────────────────────

def fill_dois(db: Any, fetch: Callable[[list[str]], dict], limit: int = DOI_LIMIT) -> str:
    """Ask PubMed again for the DOI of the papers stored without one."""
    rows = db.fetchall(DOI_PENDING_SQL, {"age": MAX_AGE_DAYS, "recheck": RECHECK_DAYS, "limit": limit})
    if not rows:
        return "no paper waits for its DOI"
    by_pmid: dict[str, list[str]] = {}
    for r in rows:
        by_pmid.setdefault(r["pmid"], []).append(r["id"])
    pmids = list(by_pmid)
    found = none = failed = 0
    for i in range(0, len(pmids), DOI_BATCH):
        batch = pmids[i:i + DOI_BATCH]
        try:
            recs = summaries(fetch(batch), batch)
        except Exception as exc:          # one bad batch never stops the others
            failed += len(batch)
            log.warning("PubMed DOIs: a batch of %d failed (%s)", len(batch), type(exc).__name__)
            continue
        with db.transaction():
            for pmid in batch:
                doi = doi_of(recs.get(pmid))
                found += bool(doi)
                none += not doi
                for doc_id in by_pmid[pmid]:
                    db.execute(DOI_STORE_SQL, {"id": doc_id, "doi": doi})
    words = f"{found} DOIs found, {none} papers still without one"
    return words + (f", {failed} to try again" if failed else "")


def check_papers(db: Any, ask: Callable[[str], dict | None], limit: int = LIMIT,
                 budget_s: float = TIME_BUDGET_S, clock: Callable[[], float] = time.monotonic) -> str:
    """Ask Unpaywall for every paper waiting and keep its answer; what was done, in words."""
    rows = db.fetchall(PENDING_SQL, {"age": MAX_AGE_DAYS, "recheck": RECHECK_DAYS, "limit": limit})
    if not rows:
        return "no paper waits for Unpaywall"
    by_doi: dict[str, list[str]] = {}
    for r in rows:
        doi = clean_doi(r["doi"])
        if doi:
            by_doi.setdefault(doi.lower(), []).append(r["id"])
    start = clock()
    opened = closed = unknown = failed = in_a_row = 0
    left = 0
    for n, (doi, ids) in enumerate(by_doi.items()):
        if clock() - start > budget_s or in_a_row >= MAX_FAILURES_IN_A_ROW:
            left = len(by_doi) - n
            break
        try:
            oa = open_access(ask(doi))
        except Exception as exc:          # one paper never stops the others
            failed += 1
            in_a_row += 1
            log.warning("Unpaywall: one paper failed (%s); it is asked again next run", type(exc).__name__)
            continue
        in_a_row = 0
        opened += oa["is_oa"]
        unknown += not oa["known"]
        closed += oa["known"] and not oa["is_oa"]
        with db.transaction():
            for doc_id in ids:
                db.execute(STORE_SQL, {"id": doc_id, "oa": json.dumps(oa)})
    words = f"{opened} papers with a free full text, {closed} without one, {unknown} not known to Unpaywall"
    if failed:
        words += f", {failed} to try again"
    if left:
        words += f", {left} wait for the next run"
    return words


def _esummary(client: Any) -> Callable[[list[str]], dict]:
    key = os.environ.get("NCBI_API_KEY")
    gap = 0.11 if key else 0.34

    def fetch(pmids: list[str]) -> dict:
        params = {"db": "pubmed", "retmode": "json", "id": ",".join(pmids), "tool": "pharos"}
        if key:
            params["api_key"] = key
        time.sleep(gap)
        res = client.get(f"{EUTILS}/esummary.fcgi", params=params)
        res.raise_for_status()
        return res.json()

    return fetch


def run(db: Any, limit: int = LIMIT) -> list[str]:
    import httpx

    out = []
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as client:
        try:
            out.append("dois: " + fill_dois(db, _esummary(client)))
        except Exception as exc:          # the lookups below still run on the DOIs already known
            out.append(f"dois: stopped ({type(exc).__name__})")
        out.append("unpaywall: " + check_papers(db, make_ask(_client_get(client)), limit=limit))
    return out


# ───────────────────────────── a case's open PDF ─────────────────────────────

def pdf_context() -> Any:
    """A fetcher for open copies: public hosts only, at most MAX_PDF_BYTES, nothing archived until checked."""
    from collectors.core.archive import Archive
    from collectors.core.context import FetchContext

    return FetchContext(None, "open-access", archive=Archive(enabled=False), public_only=True,
                        max_bytes=MAX_PDF_BYTES)


def context_get(ctx: Any) -> Callable[[str], tuple[int, bytes]]:
    """``get`` for ``make_ask`` through a FetchContext (the case reader's lookup of a paper not asked yet)."""

    def get(url: str) -> tuple[int, bytes]:
        got = ctx.get(url, accept="application/json", headers={"User-Agent": USER_AGENT}, raise_for_status=False)
        return got.status, got.content

    return get


def is_pdf(content_type: str, content: bytes) -> bool:
    """A PDF by its declared type AND its first bytes: a publisher's HTML page (a cookie wall, a sign-in) is not."""
    mime = (content_type or "").split(";")[0].strip().lower()
    return mime in PDF_TYPES and content[:5] == b"%PDF-"


def fetch_open_pdf(ctx: Any, oa: dict | None) -> tuple[bytes | None, dict | None, list[str]]:
    """The first open PDF of ``oa['pdfs']`` that arrives as a PDF: (its bytes, its location, what failed before);
    (None, None, what failed) when none does. Each failure is one host and why, never more."""
    import httpx

    from collectors.core.context import FetchError, SourceBlocked, UnsafeAddress

    tried: list[str] = []
    for loc in (oa or {}).get("pdfs") or []:
        url = _http(loc.get("pdf_url"))
        if not url:
            continue
        host = urlsplit(url).hostname or "?"
        try:
            got = ctx.get(url, accept="application/pdf,*/*;q=0.5")
        except UnsafeAddress:
            tried.append(f"{host}: not a public address, refused")
            continue
        except (FetchError, SourceBlocked, httpx.HTTPError, OSError) as exc:
            tried.append(f"{host}: {type(exc).__name__}")
            continue
        if got.status != 200 or not is_pdf(got.content_type, got.content):
            tried.append(f"{host}: not a PDF ({got.mime})")
            continue
        return got.content, loc, tried
    return None, None, tried


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.fulltext", description=__doc__.split("\n\n")[0])
    p.add_argument("--limit", type=int, default=LIMIT, help="Unpaywall lookups this run")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from collectors.core.context import install_log_redaction

    install_log_redaction()   # httpx logs request addresses at INFO: kept to warnings
    from collectors.core.db import Db

    db = Db()
    try:
        for line in run(db, limit=args.limit):
            print(line)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
