"""The free terminology loaders (migration 0103). Every code and name here is invented, in the publishers' formats."""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager

import pytest

from collectors.coding.terminology import base, ncit


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
    db, told, archive = FakeDb(size=399 * 1024 * 1024), [], FakeArchive()
    names = {f"C{i}": f"Name {i}" for i in range(2000)}
    with pytest.raises(base.TerminologyError, match="past the 400 MB"):
        base.load(db, _release(**names), min_concepts=1, archive=archive, notify=told.append)
    assert not db.inserted and not db.copied and not archive.put_calls
    assert "past the 400 MB" in told[0]


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
