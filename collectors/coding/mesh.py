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


def terms(records: list[dict]) -> dict:
    """The descriptors as term_concept records (migration 0103): a descriptor's parents are the descriptors at
    its tree numbers' parents (C06.552.380 → the one at C06.552), its tree numbers kept as its subsets."""
    from collectors.coding.terminology.base import Concept

    at = {t: r["ui"] for r in records for t in r["trees"]}
    out = {}
    for r in records:
        parents = sorted({at[t.rsplit(".", 1)[0]] for t in r["trees"] if "." in t and t.rsplit(".", 1)[0] in at})
        out[r["ui"]] = Concept(code=r["ui"], name=r["name"], definition=r["scope_note"],
                               names=[(t, "en", p) for t, p in r["terms"]], parents=parents,
                               subsets=list(r["trees"]), uri=f"http://id.nlm.nih.gov/mesh/{r['ui']}")
    return out


def to_terms(db: Any, records: list[dict], data: bytes, *, version: str, url: str,
             notify: Any = None) -> str:
    """The same release into the free-terminology tables, so one search covers every source. A failure there
    never undoes the MeSH load: it is said, and tried again on the next run."""
    from collectors.coding.terminology.base import Release, TerminologyError
    from collectors.coding.terminology.base import load as load_terms

    rel = Release(source="mesh", version=version.removeprefix("MeSH").strip() or version, url=url, data=data,
                  concepts=terms(records),
                  mime="application/gzip")
    try:
        return load_terms(db, rel, min_concepts=1000, notify=notify)
    except TerminologyError as exc:
        return f"not in the terminology search ({exc})"
    except Exception as exc:
        log.warning("MeSH into term_*: stopped (%s)", type(exc).__name__)
        return f"not in the terminology search (stopped: {type(exc).__name__})"


def load(db: Any, data: bytes | None = None, *, year: int | None = None, url: str = "", force: bool = False,
         notify: Any = None) -> str:
    """Load the newest release (or ``data``); what was done, in words. The release also goes into term_*
    (0103), once: a release already there is skipped by its SHA-256."""
    from collectors.core.archive import sha256_hex

    if data is None:
        import httpx

        with httpx.Client(timeout=120, follow_redirects=False, headers=HEADERS) as client:
            year, data, url = newest(client.get)
    sha = sha256_hex(data)
    version = f"MeSH {year}" if year else "MeSH"
    row = db.fetchone("select version, sha256 from coding_dictionary where name = 'mesh'")
    if row and row["sha256"] == sha and not force:
        said = f"{row['version']} is already loaded"
        if not db.fetchone("select 1 from term_release where source = 'mesh' and sha256 = %s", (sha,)):
            said += "; terminology search: " + to_terms(db, list(parse(data)), data, version=row["version"],
                                                         url=url, notify=notify)
        return said
    records = list(parse(data))
    counts = store(db, records, version=version, url=url, sha=sha)
    said = f"{version}: {counts['descriptors']} descriptors, {counts['terms']} names"
    return said + "; terminology search: " + to_terms(db, records, data, version=version, url=url, notify=notify)
