"""The Ontology of Adverse Events (OAE), without any of its MedDRA cross-references (migration 0103).

OAE is published as one OWL file (RDF/XML, about 12 MB) at its OBO PURL, under CC BY 4.0. PHAROS keeps each OAE
class (``obo/OAE_<digits>``) that is not deprecated, with:

    rdfs:label                       its name
    obo:IAO_0000115                  its definition
    oboInOwl:hasExactSynonym,
    oboInOwl:hasRelatedSynonym,
    obo:IAO_0000118 (alternative)    its other names (OAE's own classes use the last one)
    rdfs:subClassOf (a named class)  its parents

Nothing else is read. OAE also carries MedDRA codes (``OAE_0004334``, has_MedDRA_id), editor notes that quote them
(``IAO_0000116``) and comments; MedDRA is licensed and this repository is public, so those are never read, and any
value that still names MedDRA or carries an 8-digit code of the 100xxxxx form is dropped (a definition) or the
name left out. The licence is checked on every release: a file that is not CC BY is refused.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any, Callable

from lxml import etree

from collectors.coding.terminology.base import Concept, Release, TerminologyError, fetch, load

log = logging.getLogger("collectors.coding.terminology.oae")

URL = "http://purl.obolibrary.org/obo/oae.owl"
MIN_CONCEPTS = 5000                 # 9,403 OAE classes in the 2026-04-15 release
OBO = "http://purl.obolibrary.org/obo/"
CLASS_IRI = re.compile(r"^http://purl\.obolibrary\.org/obo/(OAE_[0-9]{7})$")
NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "obo": OBO,
    "oio": "http://www.geneontology.org/formats/oboInOwl#",
    "terms": "http://purl.org/dc/terms/",
    "xml": "http://www.w3.org/XML/1998/namespace",
}
RDF_ABOUT = f"{{{NS['rdf']}}}about"
RDF_RESOURCE = f"{{{NS['rdf']}}}resource"
XML_LANG = f"{{{NS['xml']}}}lang"
# Whatever names MedDRA or carries a code of its form never reaches the database.
MEDDRA = re.compile(r"meddra|(?<![0-9])10[0-9]{6}(?![0-9])", re.IGNORECASE)


def clean(value: str | None) -> str | None:
    """The value, or None when it is empty or touches MedDRA."""
    text = " ".join((value or "").split())
    if not text or MEDDRA.search(text):
        return None
    return text


def _english(elements: list) -> list[str]:
    return [e.text for e in elements if e.text and (e.get(XML_LANG) or "en").lower().startswith("en")]


def parse(data: bytes) -> tuple[str, dict[str, Concept]]:
    """The version and the OAE classes PHAROS keeps, by code. Raises TerminologyError."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, load_dtd=False)
    try:
        root = etree.parse(io.BytesIO(data), parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise TerminologyError("OAE: the file is not an OWL file that can be read.") from exc
    onto = root.find("owl:Ontology", NS)
    if onto is None:
        raise TerminologyError("OAE: the file has no ontology header.")
    licences = [e.get(RDF_RESOURCE) or e.text or "" for e in onto.findall("terms:license", NS)]
    if not any(re.search(r"creativecommons\.org/licenses/by/", lic) for lic in licences):
        raise TerminologyError("OAE: the file no longer says it is CC BY (it says "
                               f"{', '.join(licences)[:120] or 'nothing'}). Nothing was loaded; the licence "
                               "must be read again before this release is used.")
    version_iri = onto.find("owl:versionIRI", NS)
    found = re.search(r"/releases/([0-9]{4}-[0-9]{2}-[0-9]{2})/", (version_iri.get(RDF_RESOURCE) or "")
                      if version_iri is not None else "")
    version = found.group(1) if found else "unversioned"

    out: dict[str, Concept] = {}
    for cls in root.findall("owl:Class", NS):        # top-level classes only; nested ones are expressions
        m = CLASS_IRI.match(cls.get(RDF_ABOUT) or "")
        if not m:
            continue
        if any((d.text or "").strip().lower() == "true" for d in cls.findall("owl:deprecated", NS)):
            continue
        labels = [clean(t) for t in _english(cls.findall("rdfs:label", NS))]
        labels = [t for t in labels if t]
        if not labels:
            continue
        definition = next((d for d in (clean(t) for t in _english(cls.findall("obo:IAO_0000115", NS))) if d),
                          None)
        synonyms = [clean(t) for t in _english(cls.findall("oio:hasExactSynonym", NS)
                                               + cls.findall("oio:hasRelatedSynonym", NS)
                                               + cls.findall("obo:IAO_0000118", NS))]
        names = [(labels[0], "en", True)] + [(t, "en", False) for t in labels[1:] + [s for s in synonyms if s]]
        parents = []
        for sub in cls.findall("rdfs:subClassOf", NS):
            pm = CLASS_IRI.match(sub.get(RDF_RESOURCE) or "")
            if pm:
                parents.append(pm.group(1))
        code = m.group(1)
        out[code] = Concept(code=code, name=labels[0], definition=definition, names=names, parents=parents,
                            uri=OBO + code)
    return version, out


def release(data: bytes, *, url: str = URL) -> Release:
    version, concepts = parse(data)
    return Release(source="oae", version=version, url=url, data=data, concepts=concepts,
                   mime="application/rdf+xml")


def run(db: Any, *, data: bytes | None = None, archive: Any = None,
        notify: Callable[[str], None] | None = None, get: Callable[[str], tuple[bytes, dict]] = fetch) -> str:
    if data is None:
        data, _ = get(URL)
    return load(db, release(data), min_concepts=MIN_CONCEPTS, archive=archive, notify=notify)
