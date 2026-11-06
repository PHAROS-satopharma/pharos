"""The MeSH headings of literature papers (migration 0062).

NLM's indexers give each PubMed paper its MeSH headings, and mark an adverse effect with the qualifier "chemically
induced" (Q000139) or a heading under Chemically-Induced Disorders (C25). ``code_papers`` fetches them for the
literature papers of the last year (PubMed efetch, 200 papers a request, ``NCBI_API_KEY`` when set) and keeps them
in ``document.structured``: ``mesh`` = [{ui, name, major, q: [qualifier ui]}] and ``mesh_checked``. A paper NLM has
not indexed yet is asked again after 30 days. ``ingredient_coded_terms()`` counts them on the ingredient screen.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable

from lxml import etree

log = logging.getLogger("collectors.coding.papers")

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH = 200
RECHECK_DAYS = 30
MAX_AGE_DAYS = 365
LIMIT = 4000           # papers per run; what is left waits for the next one

PENDING_SQL = """
select d.id::text as id, d.structured ->> 'pmid' as pmid
  from document d
 where d.doc_type = 'literature'
   and coalesce(d.structured ->> 'pmid', '') ~ '^[0-9]+$'
   and d.first_seen_at >= now() - make_interval(days => %(age)s)
   and (d.structured -> 'mesh_checked' is null
        or (coalesce(jsonb_array_length(d.structured -> 'mesh'), 0) = 0
            and (d.structured ->> 'mesh_checked')::timestamptz < now() - make_interval(days => %(recheck)s)))
 order by d.first_seen_at desc
 limit %(limit)s
"""

STORE_SQL = """
update document
   set structured = coalesce(structured, '{}'::jsonb)
                    || jsonb_build_object('mesh', %(mesh)s::jsonb, 'mesh_checked', now())
 where id = %(id)s::uuid
"""


def parse(xml: bytes) -> dict[str, list[dict]]:
    """PMID -> its headings, from an efetch ``PubmedArticleSet``. A paper without headings maps to []."""
    out: dict[str, list[dict]] = {}
    root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))
    for art in root.iterfind("PubmedArticle/MedlineCitation"):
        pmid = (art.findtext("PMID") or "").strip()
        if not pmid:
            continue
        heads = []
        for h in art.iterfind("MeshHeadingList/MeshHeading"):
            d = h.find("DescriptorName")
            if d is None or not d.get("UI"):
                continue
            quals = h.findall("QualifierName")
            heads.append({"ui": d.get("UI"), "name": (d.text or "").strip(),
                          "major": d.get("MajorTopicYN") == "Y" or any(q.get("MajorTopicYN") == "Y" for q in quals),
                          "q": [q.get("UI") for q in quals if q.get("UI")]})
        out[pmid] = heads
    return out


def _post(client: Any) -> Callable[[list[str]], bytes]:
    key = os.environ.get("NCBI_API_KEY")
    gap = 0.11 if key else 0.34

    def fetch(pmids: list[str]) -> bytes:
        data = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "tool": "pharos"}
        if key:
            data["api_key"] = key
        time.sleep(gap)
        res = client.post(EFETCH, data=data)
        res.raise_for_status()
        return res.content

    return fetch


def code_papers(db: Any, fetch: Callable[[list[str]], bytes] | None = None, limit: int = LIMIT) -> str:
    """Fetch and keep the headings of every paper waiting for them; what was done, in words."""
    rows = db.fetchall(PENDING_SQL, {"age": MAX_AGE_DAYS, "recheck": RECHECK_DAYS, "limit": limit})
    if not rows:
        return "no paper waits for its MeSH headings"
    client = None
    if fetch is None:
        import httpx

        client = httpx.Client(timeout=60, headers={"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"})
        fetch = _post(client)
    by_pmid: dict[str, list[str]] = {}
    for r in rows:
        by_pmid.setdefault(r["pmid"], []).append(r["id"])
    pmids = list(by_pmid)
    indexed = waiting = failed = 0
    try:
        for i in range(0, len(pmids), BATCH):
            batch = pmids[i:i + BATCH]
            try:
                got = parse(fetch(batch))
            except Exception as exc:          # one bad batch never stops the others
                failed += len(batch)
                log.warning("PubMed headings: a batch of %d failed (%s)", len(batch), type(exc).__name__)
                continue
            with db.transaction():
                for pmid in batch:
                    heads = got.get(pmid, [])
                    indexed += bool(heads)
                    waiting += not heads
                    for doc_id in by_pmid[pmid]:
                        db.execute(STORE_SQL, {"id": doc_id, "mesh": json.dumps(heads)})
    finally:
        if client is not None:
            client.close()
    words = f"{indexed} papers indexed, {waiting} not indexed by NLM yet"
    return words + (f", {failed} to try again" if failed else "")
