"""The source document of a case opened from a literature paper: the paper's PubMed record and, when PubMed Central
holds it openly, its full text, as one text file.

Read through E-utilities with the literature collector's etiquette (``collectors/parsers/pubmed.py``), archived
under ``sha256/`` as ``text/plain`` like every original, and set on the case (``r2_key``, ``sha256``, ``mime``,
``bytes``) before the reader takes it. A paper with neither id (a preprint the Europe PMC watch found) is read from
its Europe PMC record instead: title and abstract (``collectors/parsers/europepmc.py``). A paper with none of the
three ids cannot be fetched: the case fails with a message and the reviewer uploads the article instead.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from collectors.core.archive import Archive
from collectors.core.context import FetchContext, FetchError
from collectors.parsers import europepmc
from collectors.parsers.pubmed import EUTILS, _common, _pace

log = logging.getLogger("collectors.cases.paper")

MAX_FULL_TEXT = 300_000


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


def build_text(doc: dict, abstract: str, full: str, record: str = "PubMed record") -> str:
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
    parts = ["\n".join(head), f"{record}:\n" + (abstract.strip() or "(no abstract)")]
    parts.append("Full text (PubMed Central):\n" + full if full.strip()
                 else "Full text: not openly available in PubMed Central; only the record above was read.")
    return "\n\n".join(parts)


def fetch_source(db: Any, archive: Archive, case: dict, ctx: FetchContext | None = None) -> dict:
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
    ctx = ctx or FetchContext(None, "cases", archive=archive)
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
    body = build_text(doc, abstract, full, record).encode("utf-8")
    sha, key = archive.put(body, "text/plain")
    row = db.fetchone(
        """update safety_case set r2_key = %(k)s, sha256 = %(s)s, mime = 'text/plain', bytes = %(b)s,
                  updated_at = clock_timestamp()
            where id = %(id)s returning *""",
        {"k": key, "s": sha, "b": len(body), "id": case["id"]})
    return row or case
