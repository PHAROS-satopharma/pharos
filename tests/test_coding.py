"""Medical coding (migration 0061): the MeSH loader, the product lookup and the coder's suggestions."""

from __future__ import annotations

import gzip
import json
from contextlib import contextmanager

import pytest

from collectors.coding import coder, drugs, mesh
from collectors.coding.norm import norm

MESH_XML = b"""<?xml version="1.0"?>
<!DOCTYPE DescriptorRecordSet SYSTEM "desc2026.dtd">
<DescriptorRecordSet LanguageCode="eng">
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D005076</DescriptorUI>
  <DescriptorName><String>Exanthema</String></DescriptorName>
  <TreeNumberList><TreeNumber>C17.800.229</TreeNumber><TreeNumber>C23.888.885.250</TreeNumber></TreeNumberList>
  <ConceptList>
   <Concept PreferredConceptYN="Y">
    <ConceptUI>M0007794</ConceptUI>
    <ConceptName><String>Exanthema</String></ConceptName>
    <ScopeNote>Diseases in which skin eruptions or rashes are a prominent manifestation.</ScopeNote>
    <TermList>
     <Term RecordPreferredTermYN="Y"><TermUI>T1</TermUI><String>Exanthema</String></Term>
     <Term RecordPreferredTermYN="N"><TermUI>T2</TermUI><String>Rash</String></Term>
     <Term RecordPreferredTermYN="N"><TermUI>T3</TermUI><String>RASH</String></Term>
    </TermList>
   </Concept>
   <Concept PreferredConceptYN="N">
    <ConceptUI>M2</ConceptUI>
    <ConceptName><String>Skin Rash</String></ConceptName>
    <TermList><Term RecordPreferredTermYN="N"><TermUI>T4</TermUI><String>Skin Rash</String></Term></TermList>
   </Concept>
  </ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D002338</DescriptorUI>
  <DescriptorName><String>Carvedilol</String></DescriptorName>
  <TreeNumberList><TreeNumber>D03.132.470</TreeNumber></TreeNumberList>
  <ConceptList><Concept PreferredConceptYN="Y"><ConceptUI>M3</ConceptUI><ConceptName><String>Carvedilol</String>
  </ConceptName><TermList><Term RecordPreferredTermYN="Y"><TermUI>T5</TermUI><String>Carvedilol</String></Term>
  </TermList></Concept></ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D003866</DescriptorUI>
  <DescriptorName><String>Depressive Disorder</String></DescriptorName>
  <TreeNumberList><TreeNumber>F03.600.300</TreeNumber></TreeNumberList>
  <ConceptList><Concept PreferredConceptYN="Y"><ConceptUI>M4</ConceptUI><ConceptName><String>Depressive Disorder
  </String></ConceptName><TermList><Term RecordPreferredTermYN="Y"><TermUI>T6</TermUI><String>Depressive Disorder</String>
  </Term></TermList></Concept></ConceptList>
 </DescriptorRecord>
</DescriptorRecordSet>"""


# ───────────────────────────── the words ─────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("  Hepatitis, Drug-Induced!! ", "hepatitis drug induced"),
    ("Ä Ödem", "Ä Ödem"),                       # beyond ASCII: kept as written, as the database keeps it
    ("طفح جلدي، شديد", "طفح جلدي، شديد"),
    (None, ""),
])
def test_words_are_compared_as_the_database_compares_them(text, expected):
    # The same cases as supabase/tests/medical_coding.sql and caseForm.test.ts.
    assert norm(text) == expected


# ───────────────────────────── MeSH ─────────────────────────────
def test_mesh_keeps_the_disease_and_mental_trees_with_every_name():
    got = {r["ui"]: r for r in mesh.parse(gzip.compress(MESH_XML))}
    assert set(got) == {"D005076", "D003866"}, "a drug descriptor (tree D) is not loaded"
    rash = got["D005076"]
    assert rash["trees"] == ["C17.800.229", "C23.888.885.250"]
    assert rash["scope_note"].startswith("Diseases in which skin eruptions")
    assert dict(rash["terms"]) == {"Exanthema": True, "Rash": False, "RASH": False, "Skin Rash": False}


def test_mesh_reads_plain_xml_and_never_follows_a_dtd():
    assert [r["ui"] for r in mesh.parse(MESH_XML)] == ["D005076", "D003866"]


class Res:
    def __init__(self, status: int, content: bytes = b"", data: dict | None = None) -> None:
        self.status_code, self.content, self._data = status, content, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_the_newest_release_served_is_taken():
    from datetime import date

    asked = []

    def get(url):
        asked.append(url.rsplit("/", 1)[-1])
        return Res(200, gzip.compress(MESH_XML)) if "2026" in url else Res(302)

    year, data, url = mesh.newest(get, today=date(2026, 11, 6))
    assert (year, asked) == (2026, ["desc2027.gz", "desc2026.gz"])
    assert url.endswith("/desc2026.gz") and data[:2] == b"\x1f\x8b"


# ───────────────────────────── products ─────────────────────────────
WATCHLIST = [{"id": "ing-carv", "inn_en": "Carvedilol", "rxcui": "20352", "names": ["carvedilol", "carvid", "dilatrend"]},
             {"id": "ing-melox", "inn_en": "Meloxicam", "rxcui": "41493", "names": ["meloxicam", "mobic"]}]


def rxnav_get(url, params=None):
    if url.endswith("/approximateTerm.json"):
        return Res(200, data={"approximateGroup": {"candidate": [
            {"rxcui": "315576", "source": "RXNORM"}, {"rxcui": "200033", "source": "VANDF"}]}})
    if url.endswith("/related.json"):
        rxcui = url.split("/rxcui/")[1].split("/")[0]
        if rxcui == "999":
            return Res(200, data={"relatedGroup": {"conceptGroup": [{"tty": "IN", "conceptProperties": [
                {"rxcui": "5640", "name": "ibuprofen", "tty": "IN"}, {"rxcui": "161", "name": "acetaminophen", "tty": "IN"}]}]}})
        return Res(200, data={"relatedGroup": {"conceptGroup": [{"tty": "IN", "conceptProperties": [
            {"rxcui": "20352", "name": "carvedilol", "tty": "IN"}]}]}})
    if url.endswith("/property.json"):
        return Res(200, data={"propConceptGroup": {"propConcept": [{"propName": "UNII_CODE", "propValue": "0K47UL67F2"}]}})
    raise AssertionError(url)


def test_a_brand_on_the_watchlist_is_its_ingredient_with_rxnorm_and_unii():
    got = drugs.suggest({"name": "Carvid 25 mg tablets"}, WATCHLIST, drugs.RxNav(rxnav_get))
    assert got[0]["from"] == "watchlist" and got[0]["ingredient_id"] == "ing-carv"
    assert got[0]["rxcui"] == "20352"
    assert got[0]["ingredients"] == [{"rxcui": "20352", "name": "carvedilol", "unii": "0K47UL67F2"}]
    assert "carvid" in got[0]["reason"]
    assert all(s["rxcui"] != "20352" for s in got[1:]), "RxNorm's same ingredient is not offered twice"


def test_a_word_inside_another_is_not_a_name():
    assert drugs.on_watchlist("Mobicarb syrup", WATCHLIST) == []


def test_without_rxnav_the_watchlist_still_answers():
    def down(url, params=None):
        raise ConnectionError

    got = drugs.suggest({"name": "Mobic"}, WATCHLIST, drugs.RxNav(down))
    assert [(s["name"], s["from"]) for s in got] == [("meloxicam", "watchlist")]


def test_rxnorm_answers_for_a_product_off_the_watchlist():
    got = drugs.suggest({"name": "Coreg", "active_ingredient": "carvedilol 25 mg"}, [], drugs.RxNav(rxnav_get))
    assert got[0]["from"] == "rxnorm" and got[0]["name"] == "carvedilol"
    assert "carvedilol 25 mg" in got[0]["reason"]


def test_what_the_team_chose_before_comes_first():
    got = drugs.suggest({"name": "Carvid"}, WATCHLIST, None,
                        memory=[{"code": "20352", "label": "carvedilol", "cases": 3}])
    assert got[0]["from"] == "memory" and "3 confirmed case(s)" in got[0]["reason"]
    assert len(got) == 1, "the watchlist's same code is not offered twice"


# ───────────────────────────── the coder ─────────────────────────────
DESCRIPTORS = {
    "D005076": {"ui": "D005076", "name": "Exanthema", "categories": ["Skin and Connective Tissue Diseases"]},
    "D056486": {"ui": "D056486", "name": "Chemical and Drug Induced Liver Injury", "categories": ["Digestive System Diseases"]},
    "D006973": {"ui": "D006973", "name": "Hypertension", "categories": ["Vascular Diseases"]},
    "D003920": {"ui": "D003920", "name": "Diabetes Mellitus", "categories": ["Endocrine System Diseases"]},
}
NAMES = {"rash": ["D005076"], "skin eruption": ["D005076"], "exanthema": ["D005076"],
         "hepatitis": ["D056486"], "drug induced liver injury": ["D056486"], "liver toxicity": ["D056486"],
         "hypertension": ["D006973"], "high blood pressure": ["D006973"], "diabetes": ["D003920"],
         "diabetes mellitus": ["D003920"]}


class FakeDb:
    def __init__(self, memory: dict | None = None, mesh_loaded: bool = True) -> None:
        self.memory = memory or {}
        self.mesh_loaded = mesh_loaded
        self.updates: list[dict] = []

    def fetchall(self, sql, params=None):
        if "mesh_search" in sql:
            n = norm(params[0])
            uis = [u for k, v in NAMES.items() if k in n or n in k for u in v]
            return [{**DESCRIPTORS[u], "term": u, "trees": [], "score": 0.5} for u in dict.fromkeys(uis)]
        if "coding_memory" in sql:
            return self.memory.get((params[0], norm(params[1])), [])
        if "from mesh_descriptor" in sql:
            return [DESCRIPTORS[u] for u in params[0] if u in DESCRIPTORS]
        if "from ingredient" in sql:
            return [{"id": "ing-carv", "inn_en": "Carvedilol", "rxcui": "20352", "terms": ["Carvid"]}]
        if "from safety_case" in sql:
            return [{"id": "c1", "ref": "CASE-2026-001", "data": FORM}]
        raise AssertionError(sql)

    def fetchone(self, sql, params=None):
        assert "coding_dictionary" in sql
        return {"version": "MeSH 2026"} if self.mesh_loaded else None

    def execute(self, sql, params=None):
        self.updates.append({"sql": sql, **(params or {})})

    @contextmanager
    def transaction(self):
        yield self


FORM = {
    "patient": {"medical_history": "Diabetes; high blood pressure"},
    "products": [{"name": "Carvid 25", "role": "suspect", "indication": "high blood pressure"}],
    "reactions": [{"verbatim": "طفح جلدي", "english": "skin eruption"}, {"verbatim": "liver toxicity"}],
}


class FakeReader:
    model = "claude-opus-5-5"

    def __init__(self, choose_answer: dict | None = None, fail: bool = False) -> None:
        self.choose_answer = choose_answer
        self.fail = fail
        self.asked: list = []

    def terms(self, items, history):
        if self.fail:
            raise RuntimeError("down")
        self.asked.append(("terms", [i["text"] for i in items], history))
        return {"items": [{"id": "r0", "terms": ["Exanthema"]}, {"id": "r1", "terms": ["Drug induced liver injury"]},
                          {"id": "i0", "terms": ["Hypertension"]}],
                "history": [{"condition": "Diabetes", "terms": ["Diabetes Mellitus"]},
                            {"condition": "high blood pressure", "terms": ["Hypertension"]}]}

    def choose(self, items):
        self.asked.append(("choose", {i["id"]: [c["ui"] for c in i["candidates"]] for i in items}))
        return self.choose_answer or {"items": [
            {"id": "r0", "choice": "D005076", "also": [], "reason": "A skin eruption is an exanthema."},
            {"id": "r1", "choice": "D999999", "also": ["D056486"], "reason": "Invented."},
            {"id": "i0", "choice": "D006973", "also": [], "reason": "High blood pressure is hypertension."},
            {"id": "h0", "choice": "D003920", "also": [], "reason": "Diabetes."},
            {"id": "h1", "choice": "D006973", "also": [], "reason": "Hypertension."}]}


def test_the_reader_chooses_only_among_what_mesh_returned():
    got = coder.code_form(FakeDb(), FORM, reader=FakeReader(), rx=drugs.RxNav(rxnav_get))
    by = {(i["kind"], i["index"]): i for i in got["items"]}
    rash = by[("reaction", 0)]["suggestions"]
    assert rash[0] == {"ui": "D005076", "name": "Exanthema", "categories": ["Skin and Connective Tissue Diseases"],
                       "from": "reader", "reason": "A skin eruption is an exanthema."}
    liver = by[("reaction", 1)]["suggestions"]
    assert all(s["ui"] != "D999999" for s in liver), "a code the search never returned is dropped"
    assert liver[0]["ui"] == "D056486" and liver[0]["from"] == "reader", "its alternative is kept"
    assert liver[0]["reason"] == "Another fitting descriptor.", "never the reason given for the dropped code"
    assert by[("indication", 0)]["suggestions"][0]["ui"] == "D006973"
    assert [(h["text"], h["suggestions"][0]["ui"]) for h in got["history"]] == [
        ("Diabetes", "D003920"), ("high blood pressure", "D006973")]
    assert got["products"][0]["suggestions"][0]["from"] == "watchlist"
    assert got["mesh"] == "MeSH 2026" and got["reader"] == "claude-opus-5-5" and got["note"] is None


def test_the_reader_looks_up_its_own_terms_in_mesh():
    reader = FakeReader()
    coder.code_form(FakeDb(), FORM, reader=reader, rx=None)
    candidates = next(a[1] for a in reader.asked if a[0] == "choose")
    assert candidates["r0"] == ["D005076"], "the reader is shown what MeSH returned for the words and its terms"


def test_the_team_choice_before_comes_first():
    db = FakeDb(memory={("reaction", "liver toxicity"): [{"code": "D056486", "label": "Liver injury", "cases": 2}]})
    got = coder.code_form(db, FORM, reader=None, rx=None)
    liver = next(i for i in got["items"] if i["index"] == 1 and i["kind"] == "reaction")
    assert liver["suggestions"][0]["from"] == "memory"
    assert "2 confirmed case(s)" in liver["suggestions"][0]["reason"]
    assert len({s["ui"] for s in liver["suggestions"]}) == len(liver["suggestions"]), "never the same code twice"


def test_without_the_reader_the_closest_names_still_suggest():
    got = coder.code_form(FakeDb(), FORM, reader=FakeReader(fail=True), rx=None)
    rash = next(i for i in got["items"] if i["index"] == 0 and i["kind"] == "reaction")
    assert rash["suggestions"][0]["from"] == "search" and rash["suggestions"][0]["ui"] == "D005076"
    assert got["reader"] is None and "could not be asked" in got["note"]
    assert [h["text"] for h in got["history"]] == ["Diabetes", "high blood pressure"], "split on its semicolons"


def test_without_mesh_the_products_are_still_suggested():
    got = coder.code_form(FakeDb(mesh_loaded=False), FORM, reader=None, rx=None)
    assert got["mesh"] is None and "not loaded" in got["note"]
    assert got["products"][0]["suggestions"]


def test_the_suggestions_are_written_beside_the_form_never_into_it():
    db = FakeDb()
    assert coder.code_waiting(db, make_reader=lambda: None, rx=drugs.RxNav(rxnav_get)) == {"coded": 1}
    (update,) = db.updates
    assert "set coding = " in update["sql"] and "data" not in update["sql"].split("where")[0]
    assert "updated_at" not in update["sql"], "the reviewer's open page does not go stale"
    stored = json.loads(json.dumps(update["c"].obj if hasattr(update["c"], "obj") else update["c"], default=str))
    assert stored["items"] and stored["products"]


def test_a_case_that_cannot_be_coded_says_so_and_the_others_go_on(monkeypatch):
    def boom(*a, **k):
        raise ValueError("bad form")

    monkeypatch.setattr(coder, "code_form", boom)
    db = FakeDb()
    assert coder.code_waiting(db, make_reader=lambda: None, rx=drugs.RxNav(rxnav_get)) == {"failed": 1}
    assert "coding_status = 'failed'" in db.updates[0]["sql"] and db.updates[0]["e"] == "Coding failed: ValueError"
