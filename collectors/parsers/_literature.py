"""One paper, one document, whichever literature source found it first.

PHAROS reads the literature from two sources of kind ``literature``: NCBI (``collectors/parsers/pubmed.py``: PubMed
and PubMed Central) and Europe PMC (``collectors/parsers/europepmc.py``). The two overlap: most of what Europe PMC
holds is PubMed's own records. A paper one source has stored is never stored again by the other; the other only
records that it found the paper too:

  ``structured.found_in``  gains the database that found it again ('pubmed', 'pmc' or 'europepmc')
  ``structured.queries``   each search word that found it again lists that database too (a word new to the paper
                           is added with its kind), so the Ingredients screen counts it under each database

``structured.query_term`` is left alone: the paper's matches were made when it was stored, and finding it again
by another word never links it to another ingredient. A paper is the same paper when it has the same PMID, the
same PMC id or the same DOI (DOIs compared without case, as doi.org does).
"""

from __future__ import annotations

import re
from typing import Any

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def doi_key(doi: Any) -> str | None:
    """A DOI as compared: lower case, without a doi.org prefix; None when it is not one."""
    v = _DOI_PREFIX.sub("", str(doi or "").strip()).strip().lower()
    return v if v.startswith("10.") and "/" in v else None


def found_also(structured: dict | None, db: str, queries: dict[str, str]) -> dict:
    """``structured`` (a copy) with ``db`` in ``found_in`` and in the databases of each search word of ``queries``
    (search words → name | class). The words are compared without case."""
    s = dict(structured or {})
    s["found_in"] = sorted({*(s.get("found_in") or []), db})
    have = [dict(q) for q in s.get("queries") or [] if isinstance(q, dict)]
    by_word = {str(q.get("query") or "").casefold(): q for q in have}
    for word, kind in queries.items():
        q = by_word.get(word.casefold())
        if q is None:
            q = {"query": word, "kind": kind, "db": []}
            have.append(q)
            by_word[word.casefold()] = q
        q["db"] = sorted({*(q.get("db") or []), db})
    s["queries"] = sorted(have, key=lambda q: str(q.get("query") or "").casefold())
    # a flag cleared because no name search had found the paper (collectors/case_names.py) is checked again
    # once one does
    if "name" in queries.values() and s.get("case_report") is None and isinstance(s.get("case_report_was"), dict):
        s["case_report"] = s.pop("case_report_was")
        s.pop("names_checked", None)
    return s


class Elsewhere:
    """The papers the OTHER literature sources have stored, by PMID, PMC id and DOI, and which of them this run's
    searches found again (written back by ``save``)."""

    def __init__(self, rows: list[dict]) -> None:
        self.by_pmid: dict[str, str] = {}
        self.by_pmcid: dict[str, str] = {}
        self.by_doi: dict[str, str] = {}
        for r in rows:
            doc = str(r["id"])
            ext = str(r.get("external_id") or "")
            pmid = str(r.get("pmid") or "") or (ext if ext.isdigit() else "")
            pmcid = str(r.get("pmcid") or "") or (ext if ext.startswith("PMC") else "")
            if pmid:
                self.by_pmid.setdefault(pmid, doc)
            if pmcid:
                self.by_pmcid.setdefault(pmcid, doc)
            if doi_key(r.get("doi")):
                self.by_doi.setdefault(doi_key(r.get("doi")), doc)
        self._found: dict[str, dict[str, dict[str, str]]] = {}     # db → document → search words → kind

    @classmethod
    def load(cls, store: Any, source_id: str) -> "Elsewhere":
        if store is None or not hasattr(store, "literature_papers"):
            return cls([])
        return cls(store.literature_papers(source_id))

    def ids(self) -> set[str]:
        """Every PMID and PMC id stored by another source."""
        return set(self.by_pmid) | set(self.by_pmcid)

    def find(self, pmid: str | None = None, pmcid: str | None = None, doi: str | None = None) -> str | None:
        """The document of the paper another source stored under any of these ids, if any."""
        return ((self.by_pmid.get(pmid) if pmid else None) or (self.by_pmcid.get(pmcid) if pmcid else None)
                or (self.by_doi.get(doi_key(doi) or "") if doi else None))

    def found(self, document_id: str, db: str, query: str, kind: str) -> None:
        self._found.setdefault(db, {}).setdefault(document_id, {}).setdefault(query, kind)

    def save(self, store: Any) -> int:
        """Record on each paper that this run found it again; how many papers that was."""
        if store is None or not self._found:
            return 0
        papers: set[str] = set()
        for db, docs in sorted(self._found.items()):
            store.literature_found_also(docs, db)
            papers.update(docs)
        self._found = {}
        return len(papers)
