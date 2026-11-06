"""The source document of a case opened from a literature paper: the paper's PubMed record and, when PubMed Central
holds it openly, its full text, as one text file.

Read through E-utilities with the literature collector's etiquette (``collectors/parsers/pubmed.py``), archived
under ``sha256/`` as ``text/plain`` like every original, and set on the case (``r2_key``, ``sha256``, ``mime``,
``bytes``) before the reader takes it. A paper with neither id (a preprint the Europe PMC watch found) is read from
its Europe PMC record instead: title and abstract (``collectors/parsers/europepmc.py``). A paper with none of the
three ids cannot be fetched: the case fails with a message and the reviewer uploads the article instead.

When PubMed Central holds no full text but Unpaywall lists a legal open copy as a PDF (``structured.oa``, kept by
``collectors/fulltext.py``; a paper not asked yet, or asked over 30 days ago without an open copy, is asked now),
the PDF is fetched through ``fulltext.fetch_open_pdf`` (public hosts only, a size limit, a PDF by its type and its
bytes), archived under ``sha256/`` as ``application/pdf`` with its licence, version, host type, address and DOI
in the object's metadata, and named in the text file by the line ``Open-access PDF: sha256/...``. The reader then
receives the PDF beside the text (``attached_pdf_blocks``), checked against its SHA-256 like the original. A copy
that cannot be fetched (a publisher's cookie wall, a bot check, a private address) is said in the text file, and
the record alone is read.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, urlsplit

from collectors.core.archive import Archive, sha256_hex
from collectors.core.context import FetchContext, FetchError
from collectors.parsers import europepmc
from collectors.parsers.pubmed import EUTILS, _common, _pace, clean_doi

log = logging.getLogger("collectors.cases.paper")

MAX_FULL_TEXT = 300_000
OA_LINE = "Open-access PDF:"
_OA_KEY = re.compile(r"^Open-access PDF: (sha256/([0-9a-f]{2})/([0-9a-f]{64}))$", re.MULTILINE)
PDF = "application/pdf"


def pmc_text(xml: bytes) -> str:
    """The article's title, abstract and body from a PMC efetch answer (JATS), a paragraph per line."""
    from lxml import etree

    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False))
    out: list[str] = []
    for sec in ("front//article-title", "front//abstract", "body", "back//fn-group"):
        for node in root.iterfind(f".//{sec}"):
            for el in node.iter("title", "p", "article-title", "td", "th"):
                text = " ".join("".join(el.itertext()).split())
                if text:
                    out.append(text)
    return "\n".join(out)[:MAX_FULL_TEXT]


def _oa_words(oa_pdf: dict) -> str:
    """'licence cc-by, published version, from a repository (https://...)'."""
    host = {"publisher": "the publisher", "repository": "a repository"}.get(oa_pdf.get("host_type") or "")
    bits = [f"licence {oa_pdf.get('license') or 'not stated'}",
            f"{oa_pdf['version']} version" if oa_pdf.get("version") else "version not stated"]
    if host:
        bits.append(f"from {host}")
    return ", ".join(bits) + f" ({oa_pdf.get('pdf_url') or oa_pdf.get('url') or ''})"


def build_text(doc: dict, abstract: str, full: str, oa_pdf: dict | None = None,
               record: str = "PubMed record") -> str:
    s = doc.get("structured") or {}
    head = [f"Title: {doc.get('title_orig') or ''}"]
    if s.get("authors"):
        head.append("Authors: " + ", ".join(a for a in s["authors"] if a))
    if s.get("journal") or s.get("pubdate"):
        head.append(f"Journal: {s.get('journal') or ''} {s.get('pubdate') or ''}".strip())
    for label, key in (("PMID", "pmid"), ("PMCID", "pmcid"), ("Europe PMC", "europepmc_id"), ("DOI", "doi")):
        if s.get(key):
            head.append(f"{label}: {s[key]}")
    if s.get("preprint"):
        head.append("Preprint: not peer reviewed")
    head.append(f"Link: {doc.get('url') or ''}")
    if oa_pdf and oa_pdf.get("key"):
        head.append(f"{OA_LINE} {oa_pdf['key']}")
    parts = ["\n".join(head), f"{record}:\n" + (abstract.strip() or "(no abstract)")]
    if full.strip():
        parts.append("Full text (PubMed Central):\n" + full)
    elif oa_pdf and oa_pdf.get("key"):
        parts.append("Full text: not in PubMed Central; the legal open-access copy Unpaywall lists is attached as a "
                     f"PDF ({_oa_words(oa_pdf)}).")
    elif oa_pdf:
        parts.append("Full text: not openly available in PubMed Central. Unpaywall lists an open copy "
                     f"({oa_pdf.get('url') or ''}), but PHAROS could not fetch it as a PDF; only the record above "
                     "was read.")
    else:
        parts.append("Full text: not openly available in PubMed Central; only the record above was read.")
    return "\n\n".join(parts)


def open_pdf(doc: dict, archive: Archive, ref: str, pdf_ctx: Any = None) -> dict | None:
    """The paper's open-access PDF, archived: its location, ``key``, ``sha256`` and ``bytes``. Without a ``key``
    when Unpaywall lists an open copy that could not be fetched; None when it lists none (or has no DOI)."""
    from collectors import fulltext

    s = doc.get("structured") or {}
    doi = clean_doi(s.get("doi"))
    if not doi:
        return None
    own = pdf_ctx is None
    pdf_ctx = pdf_ctx or fulltext.pdf_context()
    try:
        oa = s.get("oa")
        if fulltext.due(oa):
            try:
                oa = fulltext.open_access(fulltext.make_ask(fulltext.context_get(pdf_ctx))(doi))
            except Exception as exc:  # noqa: BLE001 - the record is still worth reading
                log.info("case %s: Unpaywall could not be asked (%s)", ref, type(exc).__name__)
                return None
        if not (isinstance(oa, dict) and oa.get("is_oa")):
            return None
        pdf, loc, tried = fulltext.fetch_open_pdf(pdf_ctx, oa)
    finally:
        if own:
            pdf_ctx.close()
    if pdf is None or loc is None:
        log.info("case %s: no open-access PDF could be fetched (%s)", ref, "; ".join(tried) or "none listed")
        return {"url": oa.get("url"), "tried": tried}
    sha, key = archive.put(pdf, PDF, meta={
        "licence": loc.get("license") or "not stated", "version": loc.get("version") or "not stated",
        "host-type": loc.get("host_type") or "not stated", "source-url": loc.get("pdf_url"), "doi": doi,
        "found-by": "Unpaywall"})
    log.info("case %s: open-access PDF archived (%d bytes, from %s)", ref, len(pdf),
             urlsplit(loc.get("pdf_url") or "").hostname)
    return {**loc, "key": key, "sha256": sha, "bytes": len(pdf)}


def attached_pdf_blocks(text: bytes, archive: Archive) -> list[dict]:
    """The reader's blocks of the open-access PDF a paper's text file names (none when it names none), read back
    from the archive and checked against the SHA-256 in its key."""
    from collectors.cases import content
    from collectors.cases.read import ReadFailed

    m = _OA_KEY.search(text.decode("utf-8", errors="replace"))
    if m is None:
        return []
    data = archive.get(m.group(1))
    if data is None:
        raise ReadFailed("The open-access PDF could not be read back from the archive.", passing=True)
    if sha256_hex(data) != m.group(3) or not m.group(3).startswith(m.group(2)):
        raise ReadFailed("The archived open-access PDF does not match its SHA-256. Upload the article.")
    return content.blocks_for(data, PDF, "The paper's open-access full text")


def fetch_source(db: Any, archive: Archive, case: dict, ctx: FetchContext | None = None,
                 pdf_ctx: Any = None) -> dict:
    """Fetch, archive and attach the paper's text; the case row as it now is."""
    from collectors.cases.read import ReadFailed

    doc = db.fetchone("select id, url, title_orig, structured from document where id = %(d)s",
                      {"d": case["document_id"]})
    if doc is None:
        raise ReadFailed("The paper behind this case no longer exists.")
    s = doc.get("structured") or {}
    pmid, pmcid, epmc = s.get("pmid"), s.get("pmcid"), s.get("europepmc_id")
    if not pmid and not pmcid and not epmc:
        raise ReadFailed("This paper has no PubMed, PMC or Europe PMC id, so PHAROS cannot fetch it. "
                         "Upload the article.")
    own = ctx is None
    ctx = ctx or FetchContext(None, "cases", archive=archive, public_only=True)
    _pace(ctx)
    record = "PubMed record" if pmid or pmcid else "Europe PMC record"
    try:
        abstract = ""
        if not pmid and not pmcid:
            abstract = europepmc.abstract(ctx, str(epmc))
        if pmid:
            abstract = ctx.get(f"{EUTILS}/efetch.fcgi?db=pubmed&id={quote(str(pmid))}&rettype=abstract"
                               f"&retmode=text{_common()}").text
        full = ""
        if pmcid:
            try:
                full = pmc_text(ctx.get(f"{EUTILS}/efetch.fcgi?db=pmc&id={quote(str(pmcid))}"
                                        f"&retmode=xml{_common()}").content)
            except (FetchError, ValueError) as exc:  # the record above is still worth reading
                log.info("case %s: no PMC full text (%s)", case["ref"], exc)
    except FetchError as exc:
        where = "PubMed" if pmid or pmcid else "Europe PMC"
        raise ReadFailed(f"{where} could not be reached ({exc}).", passing=True) from exc
    finally:
        if own:
            ctx.close()
    oa_pdf = None if full.strip() else open_pdf(doc, archive, case["ref"], pdf_ctx)
    body = build_text(doc, abstract, full, oa_pdf, record).encode("utf-8")
    sha, key = archive.put(body, "text/plain")
    row = db.fetchone(
        """update safety_case set r2_key = %(k)s, sha256 = %(s)s, mime = 'text/plain', bytes = %(b)s,
                  updated_at = clock_timestamp()
            where id = %(id)s returning *""",
        {"k": key, "s": sha, "b": len(body), "id": case["id"]})
    return row or case
