"""MeSH, the disease tree (C), mental disorders (F03), suicide, self-injury and depression, loaded into ``mesh_descriptor`` and ``mesh_term``.

NLM publishes one release a year (``desc<year>.gz``, the XML descriptors, about 17 MB). ``load()`` takes the newest
release NLM serves and replaces the dictionary in one transaction when its SHA-256 differs from the one loaded.
MeSH is NLM's, used under its terms: NLM is named as the source, never as endorsing PHAROS.
"""

from __future__ import annotations

import gzip
import io
import logging
from datetime import date
from typing import Any, Iterator

from lxml import etree

log = logging.getLogger("collectors.coding.mesh")

URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc{year}.gz"
# Diseases, mental disorders, and the behaviours a safety topic needs (suicide, self-injury; depression).
KEEP = ("C", "F03", "F01.145.126.980", "F01.145.126.350")
HEADERS = {"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"}
GZIP = bytes([0x1F, 0x8B])


def parse(data: bytes) -> Iterator[dict]:
    """Each kept descriptor: ui, name, trees, scope_note, terms [(term, preferred)]; gzip or plain XML."""
    stream = gzip.GzipFile(fileobj=io.BytesIO(data)) if data[:2] == b"\x1f\x8b" else io.BytesIO(data)
    parser = etree.iterparse(stream, tag="DescriptorRecord", resolve_entities=False, no_network=True,
                             huge_tree=True)
    for _, rec in parser:
        trees = [t.text.strip() for t in rec.iterfind("TreeNumberList/TreeNumber") if t.text]
        kept = [t for t in trees if t.startswith(KEEP)]
        if kept:
            ui = (rec.findtext("DescriptorUI") or "").strip()
            name = (rec.findtext("DescriptorName/String") or "").strip()
            note = None
            terms: dict[str, bool] = {}
            for concept in rec.iterfind("ConceptList/Concept"):
                concept_preferred = concept.get("PreferredConceptYN") == "Y"
                if concept_preferred and note is None:
                    note = (concept.findtext("ScopeNote") or "").strip() or None
                for term in concept.iterfind("TermList/Term"):
                    text = (term.findtext("String") or "").strip()
                    if text:
                        terms[text] = terms.get(text, False) or term.get("RecordPreferredTermYN") == "Y"
            terms.setdefault(name, True)
            yield {"ui": ui, "name": name, "trees": kept, "scope_note": note, "terms": sorted(terms.items())}
        rec.clear()
        while rec.getprevious() is not None:
            del rec.getparent()[0]


def store(db: Any, records: list[dict], *, version: str, url: str, sha: str) -> dict[str, int]:
    """Replace the dictionary with ``records`` in one transaction; counts."""
    from collectors.coding.norm import norm

    terms = 0
    with db.transaction():
        db.execute("delete from mesh_descriptor")
        with db.conn.cursor() as cur:
            with cur.copy("copy mesh_descriptor (ui, name, trees, scope_note) from stdin") as cp:
                for r in records:
                    cp.write_row((r["ui"], r["name"], r["trees"], r["scope_note"]))
            with cur.copy("copy mesh_term (ui, term, preferred) from stdin") as cp:
                for r in records:
                    seen: set[str] = set()
                    for term, preferred in sorted(r["terms"], key=lambda t: not t[1]):
                        key = norm(term)
                        if key and key not in seen:     # (ui, norm) is the key: one row per spelling
                            seen.add(key)
                            cp.write_row((r["ui"], term, preferred))
                            terms += 1
        db.execute(
            """insert into coding_dictionary (name, version, source_url, sha256, descriptors, terms, loaded_at)
               values ('mesh', %(v)s, %(u)s, %(s)s, %(d)s, %(t)s, now())
               on conflict (name) do update set version = excluded.version, source_url = excluded.source_url,
                      sha256 = excluded.sha256, descriptors = excluded.descriptors, terms = excluded.terms,
                      loaded_at = excluded.loaded_at""",
            {"v": version, "u": url, "s": sha, "d": len(records), "t": terms})
    return {"descriptors": len(records), "terms": terms}


def newest(get: Any, today: date | None = None) -> tuple[int, bytes, str]:
    """The newest release NLM serves (next year's appears late in the year): (year, bytes, url)."""
    year = (today or date.today()).year + 1
    for y in (year, year - 1, year - 2):
        url = URL.format(year=y)
        res = get(url)
        # NLM labels the file Content-Encoding: x-gzip, so the client may hand back the XML unpacked.
        body = res.content
        if res.status_code == 200 and (body[:2] == GZIP or b"<DescriptorRecordSet" in body[:4096]):
            return y, res.content, url
        log.info("MeSH %d: not served yet (HTTP %s)", y, res.status_code)
    raise RuntimeError("NLM serves no MeSH release of the last two years")


def load(db: Any, data: bytes | None = None, *, year: int | None = None, url: str = "", force: bool = False) -> str:
    """Load the newest release (or ``data``); what was done, in words."""
    from collectors.core.archive import sha256_hex

    if data is None:
        import httpx

        with httpx.Client(timeout=120, follow_redirects=False, headers=HEADERS) as client:
            year, data, url = newest(client.get)
    sha = sha256_hex(data)
    version = f"MeSH {year}" if year else "MeSH"
    row = db.fetchone("select version, sha256 from coding_dictionary where name = 'mesh'")
    if row and row["sha256"] == sha and not force:
        return f"{row['version']} is already loaded"
    counts = store(db, list(parse(data)), version=version, url=url, sha=sha)
    return f"{version}: {counts['descriptors']} descriptors, {counts['terms']} names"
