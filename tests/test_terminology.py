"""The free terminology loaders (migration 0103). Every code and name here is invented, in the publishers' formats."""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager

import pytest

from collectors.coding.terminology import base, icd11, ncit, oae


def _line(code, parents="", synonyms="", definition="", display="", status="", subsets=""):
    iri = f"<http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#{code}>"
    return "\t".join([code, iri, parents, synonyms, definition, display, status, "Finding", subsets])


NCIT = "\n".join([
    _line("C41331", "C36291", "Adverse Event|AE", "Any unfavourable event."),
    _line("C7057", "", "Disease, Disorder or Finding"),
    _line("C36291", "", "Outside Branch"),
    _line("C9000010", "C41331", "Test Sleep Problem|Test Sleeplessness|Test Sleeplessness", "Cannot sleep."),
    _line("C9000011", "C9000010|C9000099", "Test Early Waking", display="Early Waking (test)"),
    _line("C9000012", "C9000010", "Test Retired Sleep", status="Retired_Concept"),
    _line("C9000013", "C9000012", "Test Under Retired"),
    _line("C9000020", "C7057", "Test Rash"),
    _line("C9000030", "C99999", "Test Nausea, CTCAE 6.0|Test Nausea", "Queasy.",
          subsets="CTCAE Adverse Events Version 6.0 Terminology"),
    _line("C9000031", "C9000030", "Grade 1 Test Nausea, CTCAE 6.0", "Loss of appetite.",
          subsets="CTCAE Adverse Events Version 6.0 Terminology"),
    _line("C9000040", "C36291", "Test Procedure"),
    "short\tline",
]) + "\n"


def _zip(text: str, name: str = "Thesaurus.txt") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo(name, date_time=(2099, 10, 28, 19, 28, 0))
        zf.writestr(info, text)
    return buf.getvalue()


def test_ncit_keeps_the_two_branches_and_ctcae_and_nothing_else():
    got = ncit.parse(NCIT)
    assert sorted(got) == ["C41331", "C7057", "C9000010", "C9000011", "C9000013", "C9000020", "C9000030",
                           "C9000031"]
    # Outside the branches: the parent of Adverse Event, a procedure. Retired: left out.
    assert "C36291" not in got and "C9000040" not in got and "C9000012" not in got


def test_ncit_reads_the_first_synonym_as_the_name_and_keeps_the_others():
    sleep = ncit.parse(NCIT)["C9000010"]
    assert sleep.name == "Test Sleep Problem"
    assert sleep.definition == "Cannot sleep."
    assert sleep.uri == "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl#C9000010"
    waking = ncit.parse(NCIT)["C9000011"]
    assert ("Early Waking (test)", "en", False) in waking.names


def test_ncit_release_from_the_zip_is_named_by_the_file_date():
    rel = ncit.release(_zip(NCIT))
    assert (rel.source, rel.version) == ("ncit", "2099-10-28")
    assert "C9000031" in rel.concepts


def test_ncit_without_its_branches_is_refused():
    with pytest.raises(base.TerminologyError, match="branch is missing"):
        ncit.parse(_line("C9000001", "", "Lonely") + "\n")
    with pytest.raises(base.TerminologyError, match="no Thesaurus.txt"):
        ncit.release(_zip(NCIT, name="Other.txt"))


def test_validate_keeps_parents_inside_the_release_and_one_name_a_spelling():
    got = base.validate("ncit", ncit.parse(NCIT), min_concepts=1)
    assert got["C9000011"].parents == ["C9000010"]          # C9000099 is outside what PHAROS keeps
    assert got["C41331"].parents == []
    assert got["C9000013"].parents == []                    # its parent was retired
    names = got["C9000010"].names
    assert names[0] == ("Test Sleep Problem", "en", True)
    assert [n[0] for n in names].count("Test Sleeplessness") == 1
    assert sum(1 for n in names if n[2]) == 1


def test_validate_refuses_a_short_file_and_a_bad_code():
    with pytest.raises(base.TerminologyError, match="fewer than"):
        base.validate("ncit", ncit.parse(NCIT), min_concepts=100)
    bad = {"C 1": base.Concept(code="C 1", name="x")}
    with pytest.raises(base.TerminologyError, match="not well formed"):
        base.validate("ncit", bad, min_concepts=1)


def _concepts(**names) -> dict[str, base.Concept]:
    out = {code: base.Concept(code=code, name=name) for code, name in names.items()}
    return base.validate("ncit", out, min_concepts=1)


def _snap(c: base.Concept, status: str = "current") -> dict:
    return {**c.snapshot(), "status": status}


def test_diff_names_what_was_added_changed_retired_and_revived():
    old_c = _concepts(C1="Same", C2="Old name", C3="Going away", C4="Was retired")
    old = {k: _snap(v) for k, v in old_c.items()}
    old["C4"]["status"] = "retired"
    new = _concepts(C1="Same", C2="New name", C4="Was retired", C5="Brand new")
    got = {c["code"]: c["kind"] for c in base.diff(old, new)}
    assert got == {"C2": "changed", "C3": "retired", "C4": "changed", "C5": "added"}
    assert base.diff(old, new)[0]["after"]["names"] == [["New name", "en", True]]


def test_diff_of_the_same_release_is_empty():
    c = _concepts(C1="A", C2="B")
    assert base.diff({k: _snap(v) for k, v in c.items()}, _concepts(C1="A", C2="B")) == []


class FakeDb:
    """Enough of collectors.core.db.Db for load(): what was asked and what was copied."""

    def __init__(self, *, active=False, seen=None, size=0, current=None):
        self.active, self.seen, self.size = active, seen, size
        self.current = current or {}
        self.copied: dict[str, list[tuple]] = {}
        self.executed: list[str] = []
        self.inserted: list[dict] = []
        self.conn = self

    @contextmanager
    def transaction(self):
        yield self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @contextmanager
    def copy(self, sql: str):
        rows = self.copied.setdefault(sql.split()[1], [])

        class W:
            def write_row(self, row):
                rows.append(row)

        yield W()

    def fetchone(self, sql, params=None):
        if "sha256 = %s" in sql:
            return self.seen
        if "version = %s" in sql:
            return None
        if "status = 'active'" in sql:
            return {"?column?": 1} if self.active else None
        if "pg_database_size" in sql:
            return {"n": self.size}
        if sql.lstrip().startswith("insert into term_release"):
            self.inserted.append(params)
            return {"id": 7}
        raise AssertionError(sql)

    def fetchall(self, sql, params=None):
        if "from term_concept" in sql:
            return [{"code": k, "name": v["name"], "definition": v["definition"], "lang": v["lang"],
                     "status": v["status"], "subsets": v["subsets"], "uri": v["uri"]} for k, v in self.current.items()]
        if "from term_name" in sql:
            return [{"code": k, "name": n[0], "lang": n[1], "preferred": n[2]}
                    for k, v in self.current.items() for n in v["names"]]
        if "from term_parent" in sql:
            return [{"code": k, "parent": p} for k, v in self.current.items() for p in v["parents"]]
        raise AssertionError(sql)

    def execute(self, sql, params=None):
        self.executed.append(" ".join(sql.split()))


class FakeArchive:
    def __init__(self):
        self.put_calls = []

    def put(self, content, mime, meta=None):
        self.put_calls.append((len(content), mime, meta))
        return "f" * 64, "sha256/ff/" + "f" * 64


def _release(**names) -> base.Release:
    return base.Release(source="ncit", version="2099-10-28", url=ncit.URL, data=repr(names).encode(),
                        concepts={k: base.Concept(code=k, name=v) for k, v in names.items()})


def test_the_first_release_is_applied_at_once_and_archived():
    db, archive, told = FakeDb(), FakeArchive(), []
    said = base.load(db, _release(C1="A", C2="B"), min_concepts=1, archive=archive, notify=told.append)
    assert "loaded (the first release)" in said
    assert db.inserted[0]["st"] == "active" and db.inserted[0]["k"].startswith("sha256/")
    assert [r[1] for r in db.copied["term_concept"]] == ["C1", "C2"]
    assert all(r[6] == 7 for r in db.copied["term_concept"])          # first_release
    assert archive.put_calls and archive.put_calls[0][2]["source"] == "ncit"
    assert told and told[0].startswith("Terminology: NCI Thesaurus 2099-10-28")


def test_a_later_release_is_staged_with_its_differences_and_applies_nothing():
    old = {k: _snap(v) for k, v in _concepts(C1="A", C2="B").items()}
    db, told = FakeDb(active=True, current=old), []
    said = base.load(db, _release(C1="A", C2="B changed", C3="C"), min_concepts=1, notify=told.append)
    assert "1 added, 1 changed, 0 retired, waiting" in said
    assert db.inserted[0]["st"] == "staged"
    assert "term_concept" not in db.copied and "term_name" not in db.copied
    assert sorted(r[2] for r in db.copied["term_change"]) == ["C2", "C3"]
    assert any("status = 'rejected'" in sql for sql in db.executed)   # an older staged one gives way
    assert "Terminology screen" in told[0]


def test_a_later_release_without_differences_is_recorded_as_active():
    old = {k: _snap(v) for k, v in _concepts(C1="A").items()}
    db = FakeDb(active=True, current=old)
    said = base.load(db, _release(C1="A"), min_concepts=1)
    assert "no differences" in said and db.inserted[0]["st"] == "active"
    assert "term_change" not in db.copied


def test_a_release_seen_before_is_nothing_to_do():
    db = FakeDb(seen={"version": "2099-09-30", "status": "active"})
    assert base.load(db, _release(C1="A"), min_concepts=1) == "NCI Thesaurus 2099-09-30 was seen already (active)"
    assert not db.inserted


def test_a_release_that_retires_too_much_is_refused_and_the_admins_told():
    old = {k: _snap(v) for k, v in _concepts(**{f"C{i}": f"Name {i}" for i in range(1, 101)}).items()}
    db, told = FakeDb(active=True, current=old), []
    with pytest.raises(base.TerminologyError, match="would retire 99 of 100"):
        base.load(db, _release(C1="A"), min_concepts=1, notify=told.append)
    assert not db.inserted and told and "would retire" in told[0]


def test_a_release_past_the_space_allowed_is_refused_and_nothing_written():
    db, told, archive = FakeDb(size=329 * 1024 * 1024), [], FakeArchive()
    names = {f"C{i}": f"Name {i}" for i in range(2000)}
    with pytest.raises(base.TerminologyError, match="past the 330 MB"):
        base.load(db, _release(**names), min_concepts=1, archive=archive, notify=told.append)
    assert not db.inserted and not db.copied and not archive.put_calls
    assert "past the 330 MB" in told[0]


def test_a_message_that_cannot_go_never_stops_the_load():
    def broken(text):
        raise RuntimeError("telegram down")

    said = base.load(FakeDb(), _release(C1="A"), min_concepts=1, notify=broken)
    assert "loaded" in said


def test_the_cli_says_why_a_terminology_failed_without_the_database_message(monkeypatch, capsys):
    from collectors.coding import __main__ as cli

    class Boom(Exception):
        pass

    def run(db, **k):
        raise Boom("COPY term_name, line 3: secret words")

    monkeypatch.setattr(ncit, "run", run)
    monkeypatch.setattr(base, "default_notify", lambda db: None)
    assert cli.terminology(object(), "ncit", None) == 1
    out = capsys.readouterr().out
    assert "the load stopped (Boom)" in out and "secret words" not in out


def test_arabic_vowel_marks_make_one_spelling_as_in_the_database():
    assert base.norm("الكُوليرا") == base.norm("الكوليرا") == "الكوليرا"
    assert base.norm("Test-Cholera ") == "test cholera"
    c = base.Concept(code="9A00", name="Test cholera", names=[("الكُوليرا", "ar", True), ("الكوليرا", "ar", False)])
    base.clean_names(c)
    assert [n[1] for n in c.names] == ["en", "ar"]          # one Arabic row, or the database key would refuse two
# ───────────── OAE: CC BY, and nothing of MedDRA ─────────────
# The MedDRA-looking codes below are invented (10999991…), in the form OAE writes them.
OAE = b"""<?xml version="1.0"?>
<rdf:RDF xmlns="http://purl.obolibrary.org/obo/oae.owl#"
     xmlns:obo="http://purl.obolibrary.org/obo/"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
     xmlns:terms="http://purl.org/dc/terms/"
     xmlns:oboInOwl="http://www.geneontology.org/formats/oboInOwl#">
    <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/oae.owl">
        <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/oae/releases/2099-04-15/oae.owl"/>
        <terms:license rdf:resource="http://creativecommons.org/licenses/by/4.0/"/>
    </owl:Ontology>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/OAE_9000001">
        <rdfs:label xml:lang="en">test adverse event</rdfs:label>
        <obo:IAO_0000115>a test pathological bodily process</obo:IAO_0000115>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/OAE_9000002">
        <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/OAE_9000001"/>
        <rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/BFO_0000015"/>
        <rdfs:subClassOf>
            <owl:Restriction>
                <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/OAE_0000025"/>
                <owl:someValuesFrom>
                    <owl:Class rdf:about="http://purl.obolibrary.org/obo/OAE_9000099"/>
                </owl:someValuesFrom>
            </owl:Restriction>
        </rdfs:subClassOf>
        <obo:OAE_0004334>10999991</obo:OAE_0004334>
        <obo:IAO_0000116>YH: MedDRA: 10999992 is for "test sleeplessness"</obo:IAO_0000116>
        <rdfs:comment>Test comment, MedDRA ID of 10999993.</rdfs:comment>
        <obo:IAO_0000115>a test insomnia AE (MedDRA 10999994)</obo:IAO_0000115>
        <oboInOwl:hasExactSynonym>test sleeplessness AE</oboInOwl:hasExactSynonym>
        <oboInOwl:hasRelatedSynonym>MedDRA: 10999995</oboInOwl:hasRelatedSynonym>
        <oboInOwl:hasRelatedSynonym>test wakefulness AE</oboInOwl:hasRelatedSynonym>
        <obo:IAO_0000118>test sleep loss AE</obo:IAO_0000118>
        <obo:IAO_0000118>MedDRA: 10999997</obo:IAO_0000118>
        <oboInOwl:hasDbXref>MedDRA:10999996</oboInOwl:hasDbXref>
        <rdfs:label xml:lang="en">test insomnia AE</rdfs:label>
        <rdfs:label xml:lang="zh">\xe6\xb5\x8b\xe8\xaf\x95</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/OAE_9000003">
        <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
        <rdfs:label>obsolete test AE</rdfs:label>
    </owl:Class>
    <owl:Class rdf:about="http://purl.obolibrary.org/obo/UBERON_0000001">
        <rdfs:label>test body part</rdfs:label>
    </owl:Class>
</rdf:RDF>
"""


def test_oae_keeps_its_own_classes_with_label_definition_synonyms_and_parents():
    version, got = oae.parse(OAE)
    assert version == "2099-04-15"
    assert sorted(got) == ["OAE_9000001", "OAE_9000002"]          # deprecated and imported classes left out
    ins = got["OAE_9000002"]
    assert ins.name == "test insomnia AE"
    assert ins.parents == ["OAE_9000001"]                          # never a restriction or another ontology
    assert [n[0] for n in ins.names] == ["test insomnia AE", "test sleeplessness AE", "test wakefulness AE",
                                       "test sleep loss AE"]
    assert got["OAE_9000001"].definition == "a test pathological bodily process"


def test_no_meddra_code_or_word_from_oae_reaches_the_database():
    db = FakeDb()
    base.load(db, oae.release(OAE), min_concepts=1)
    stored = repr(db.copied) + repr(db.inserted)
    assert "MedDRA" not in stored and "meddra" not in stored.lower()
    for code in ("10999991", "10999992", "10999993", "10999994", "10999995", "10999996", "10999997"):
        assert code not in stored
    assert db.copied["term_concept"][1][3] is None                 # the definition that named MedDRA: dropped


def test_oae_is_refused_once_it_is_not_cc_by():
    for licence in (b"http://creativecommons.org/licenses/by-nc/4.0/", b"http://example.test/all-rights"):
        data = OAE.replace(b"http://creativecommons.org/licenses/by/4.0/", licence)
        with pytest.raises(base.TerminologyError, match="no longer says it is CC BY"):
            oae.parse(data)
    with pytest.raises(base.TerminologyError, match="no longer says it is CC BY"):
        oae.parse(OAE.replace(b'<terms:license rdf:resource="http://creativecommons.org/licenses/by/4.0/"/>', b""))


def test_oae_never_reads_an_external_entity():
    evil = OAE.replace(b'<?xml version="1.0"?>',
                       b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>')
    evil = evil.replace(b"a test pathological bodily process", b"&x;")
    _, got = oae.parse(evil)
    assert "root:" not in (got["OAE_9000001"].definition or "")


# ───────────── ICD-11: stored as WHO publishes it ─────────────
EN_HEAD = ("﻿Foundation URI\tLinearization URI\tCode\tBlockId\tTitle\tClassKind\tDepthInKind\tIsResidual\t"
           "ChapterNo\tBrowserLink\tisLeaf\tPrimary tabulation\tGrouping1\tGrouping2\tGrouping3\tGrouping4\t"
           "Grouping5\tCodingNote\tParent\tVersion:2099 Jan 17 - 05:30 UTC")
E, L = "http://id.who.int/icd/entity/", "http://id.who.int/icd/release/11/mms/"


def _icd_row(fid, code, block, title, kind, chapter, parent="", residual="False", note="", ar=None):
    cols = [E + fid, L + fid + ("/other" if residual == "True" else ""), code, block, f'"{title}"']
    if ar is not None:
        cols.append(f'"{ar}"')
    cols += [kind, "1", residual, chapter, '"=hyperlink(""https://icd.who.int/browse"",""browser"")"', "False",
             "", "", "", "", "", "", note, E + parent if parent else ""]
    return "\t".join(cols)


ICD_EN = "\n".join([
    EN_HEAD,
    _icd_row("9001", "", "", "Test infectious diseases", "chapter", "01"),
    _icd_row("9002", "", "BlockL1-9A0", "- Test intestinal infections", "block", "01", "9001"),
    _icd_row("9003", "9A00", "", "- - Test cholera", "category", "01", "9002",
             note="Use additional code, if desired.\nA second line of the note."),
    _icd_row("9003", "9A0Y", "", "- - - Other specified test cholera", "category", "01", "9003", residual="True"),
    _icd_row("9004", "", "", "Test functioning section", "chapter", "V"),
    _icd_row("9005", "", "", "- Test functioning block without a BlockId", "block", "V", "9004"),
]) + "\n"
ICD_AR = "\n".join([
    EN_HEAD.replace("\tTitle\t", "\tTitleEN\tTitle\t"),
    _icd_row("9003", "9A00", "", "- - Test cholera", "category", "01", "9002", ar="- - كوليرا تجريبية"),
]) + "\n"


def _icd_zip(text: str, lang: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(f"SimpleTabulation-ICD-11-MMS-{lang}.txt", (2099, 1, 27, 12, 44, 0)), text)
        zf.writestr("readme.txt", "test")
    return buf.getvalue()


def test_icd11_keeps_codes_titles_and_uris_unchanged_with_arabic():
    got = icd11.parse(ICD_EN, ICD_AR)
    assert sorted(got) == ["01", "9005", "9A00", "9A0Y", "BlockL1-9A0", "V"]
    cholera = got["9A00"]
    assert cholera.name == "Test cholera"                          # only the depth dashes are taken off
    assert ("كوليرا تجريبية", "ar", True) in cholera.names
    assert cholera.uri == L + "9003"
    assert cholera.parents == ["BlockL1-9A0"] and got["BlockL1-9A0"].parents == ["01"]
    assert got["9A0Y"].parents == ["9A00"]                         # a residual hangs under its category
    assert got["9005"].parents == ["V"] and got["9005"].subsets == ["block"]
    assert cholera.definition is None                              # nothing is written for WHO


def test_icd11_newest_is_the_latest_january_folder_served():
    asked = []

    def get(url):
        asked.append(url)
        if "/2099-01/" in url or "/2098-01/" in url:
            raise base.TerminologyError("HTTP 404")
        return (_icd_zip(ICD_EN, "en") if url.endswith("-en.zip") else _icd_zip(ICD_AR, "ar")), {}

    folder, files = icd11.newest(get, today=icd11.date(2098, 11, 8))
    assert folder == "2097-01" and set(files) == {"en", "ar"}
    rel = icd11.release(folder, files)
    assert rel.version == "2097-01" and len(rel.extra) == 1
    db, archive = FakeDb(), FakeArchive()
    base.load(db, rel, min_concepts=1, archive=archive)
    assert len(archive.put_calls) == 2                             # the English and the Arabic originals


def test_icd11_is_never_compared_with_another_source():
    from pathlib import Path

    sql = Path("supabase/migrations/0103_terminology.sql").read_text()
    assert "'icd11', 'ICD-11 MMS'" in sql and "Stored unchanged.',\n   false)" in sql


# ───────────── MeSH into term_* ─────────────
def test_mesh_descriptors_become_concepts_with_tree_parents():
    from collectors.coding import mesh

    records = [
        {"ui": "D000001", "name": "Test Diseases", "trees": ["C01"], "scope_note": None,
         "terms": [("Test Diseases", True)]},
        {"ui": "D000002", "name": "Test Insomnia", "trees": ["C01.100", "F03.200"], "scope_note": "Cannot sleep.",
         "terms": [("Test Insomnia", True), ("Test Sleeplessness", False)]},
    ]
    got = mesh.terms(records)
    assert got["D000002"].parents == ["D000001"] and got["D000001"].parents == []
    assert got["D000002"].subsets == ["C01.100", "F03.200"]
    assert got["D000002"].definition == "Cannot sleep."
    rel = base.Release(source="mesh", version="MeSH 2099", url="x", data=b"x", concepts=got)
    base.validate("mesh", rel.concepts, min_concepts=1)
    assert [n[0] for n in got["D000002"].names] == ["Test Insomnia", "Test Sleeplessness"]


# ───────────── no free code reaches the E2B file ─────────────
def test_a_free_code_never_reaches_the_e2b_file_nor_stands_in_for_meddra():
    from collectors.cases import e2b
    from tests.test_cases import CONFIRMED

    term = {"source": "ncit", "code": "C9000002", "name": "Test Insomnia", "version": "2099-10-28",
            "coded_by": "CI Reviewer", "coded_at": "2099-11-08T10:00:00Z"}
    reaction = {**CONFIRMED["data"]["reactions"][0], "term": term}
    case = {**CONFIRMED, "data": {**CONFIRMED["data"], "reactions": [reaction]}}
    xml = e2b.build_xml(case).decode("utf-8")
    assert "C9000002" not in xml and "Test Insomnia" not in xml and "ncit" not in xml.lower()

    only_free = {**case, "data": {**case["data"], "reactions": [{**reaction, "meddra_llt_code": "",
                                                                  "meddra_version": ""}]}}
    with pytest.raises(e2b.CannotMake, match="reaction 1 needs its MedDRA LLT code"):
        e2b.build_xml(only_free)
