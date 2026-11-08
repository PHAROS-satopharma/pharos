"""The MedDRA loader (migration 0102). Every code and term here is invented: MedDRA's own are licensed and never
belong in this public repository."""

from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager

import pytest

from collectors.coding import meddra

RELEASE = b"99.1$English$$$$\n"
PT = (b"90000001$Test sleeplessness$$90000100$$$$$$$$\n"
      b"90000002$Test itching$$90000200$$$$$$$$\n")
# Sleeplessness sits under two SOCs; the second line is its primary path.
HIER = (b"90000001$90000010$90000020$90000300$Test sleeplessness$Test sleep HLT$Test sleep HLGT$Test other SOC$TOS$$90000100$N$\n"
        b"90000001$90000011$90000021$90000100$Test sleeplessness$Test sleep HLT$Test sleep HLGT$Test mind SOC$TMS$$90000100$Y$\n"
        b"90000002$90000012$90000022$90000200$Test itching$Test itch HLT$Test itch HLGT$Test skin SOC$TSS$$90000200$Y$\n")
LLT = (b"90000001$Test sleeplessness$90000001$$$$$$$Y$$\n"
       b"90000003$Test cannot sleep$90000001$$$$$$$Y$$\n"
       b"90000004$Test old sleep word$90000001$$$$$$$N$$\n"
       b"90000002$Test itching$90000002$$$$$$$Y$$\n")
FILES = {"meddra_release.asc": RELEASE, "pt.asc": PT, "mdhier.asc": HIER, "llt.asc": LLT}


def _zip(files: dict[str, bytes], folder: str = "MedDRA_99_1_English/MedAscii/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in files.items():
            zf.writestr(folder + name, body)
        zf.writestr("MedDRA_99_1_English/readme.pdf", b"%PDF-")
    return buf.getvalue()


def test_the_release_is_read_with_each_pt_on_its_primary_path():
    parsed = meddra.parse(FILES)
    assert (parsed["version"], parsed["language"]) == ("99.1", "English")
    sleep = parsed["pts"]["90000001"]
    assert (sleep["soc_code"], sleep["soc_name"], sleep["hlt_code"]) == ("90000100", "Test mind SOC", "90000011")
    assert [(x["code"], x["current"]) for x in parsed["llts"]] == [
        ("90000001", True), ("90000003", True), ("90000004", False), ("90000002", True)]


def test_the_zip_as_msso_sends_it_is_read_from_its_medascii_folder():
    files = meddra.files_of_zip(_zip(FILES))
    assert set(files) == set(meddra.NEEDED)
    assert meddra.parse(files)["version"] == "99.1"


def test_a_zip_inside_the_zip_is_opened():
    outer = _zip({"MedAscii.zip": _zip(FILES)}, folder="")
    assert set(meddra.files_of_zip(outer)) == set(meddra.NEEDED)


def test_a_locked_zip_says_how_to_upload_it(monkeypatch):
    data = _zip(FILES)
    real = zipfile.ZipFile.infolist

    def locked(self):
        infos = real(self)
        for i in infos:
            i.flag_bits |= 0x1
        return infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", locked)
    with pytest.raises(meddra.MeddraError, match="password"):
        meddra.files_of_zip(data)


def test_a_missing_file_is_named():
    with pytest.raises(meddra.MeddraError, match="mdhier.asc"):
        meddra.parse({k: v for k, v in FILES.items() if k != "mdhier.asc"})


def test_files_of_two_releases_are_refused():
    with pytest.raises(meddra.MeddraError, match="two releases"):
        meddra.parse({**FILES, "llt.asc": LLT + b"90000009$Test stray$90000999$$$$$$$Y$$\n"})


def test_a_file_that_is_not_meddra_is_refused():
    with pytest.raises(meddra.MeddraError, match="version"):
        meddra.parse({**FILES, "meddra_release.asc": b"hello\n"})
    with pytest.raises(meddra.MeddraError, match="not a zip"):
        meddra.files_of_zip(b"not a zip")


class FakeDb:
    def __init__(self, waiting: list[str], objects: dict[str, list[str]]):
        self.waiting = waiting
        self.objects = objects
        self.calls: list[tuple[str, object]] = []
        self.copied: dict[str, list[tuple]] = {}
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
        table = sql.split()[1]
        rows = self.copied.setdefault(table, [])

        class W:
            def write_row(self, row):
                rows.append(row)

        yield W()

    def fetchall(self, sql: str, params=None):
        if "from meddra_upload" in sql:
            return [{"folder": f} for f in self.waiting]
        if "storage.objects" in sql:
            folder = params[0][:-2]
            return [{"name": n} for n in self.objects.get(folder, [])]
        raise AssertionError(sql)

    def execute(self, sql: str, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def status(self, folder: str) -> tuple[str, str]:
        for sql, params in reversed(self.calls):
            if sql.startswith("update meddra_upload set status") and params and params[-1] == folder:
                status = sql.split("'")[1]
                return status, (params[0] if len(params) > 1 else "")
        return "waiting", ""


def test_the_newest_upload_is_loaded_and_the_older_one_replaced():
    new, old = "uploads/20261110T080000Z", "uploads/20261109T080000Z"
    db = FakeDb([new, old], {new: [f"{new}/MedDRA_99_1_English.zip"]})
    said = meddra.load_waiting(db, get=lambda name: _zip(FILES))
    assert said.endswith("4 Lowest Level Terms under 2 Preferred Terms")
    assert db.status(new) == ("loaded", "MedDRA 99.1 English: 4 Lowest Level Terms under 2 Preferred Terms")
    assert any("'replaced'" in sql and params == ([old],) for sql, params in db.calls)
    assert len(db.copied["meddra_llt"]) == 4 and len(db.copied["meddra_pt"]) == 2
    dictionary = next(p for s, p in db.calls if s.startswith("insert into coding_dictionary"))
    assert (dictionary["v"], dictionary["r"], dictionary["u"]) == ("MedDRA 99.1 English", "99.1", new)


def test_the_loose_asc_files_load_as_well_as_the_zip():
    folder = "uploads/20261110T080000Z"
    db = FakeDb([folder], {folder: [f"{folder}/{n}" for n in FILES]})
    meddra.load_waiting(db, get=lambda name: FILES[name.rsplit("/", 1)[-1]])
    assert db.status(folder)[0] == "loaded"


def test_a_wrong_upload_says_why_on_the_screen_and_loads_nothing():
    folder = "uploads/20261110T080000Z"
    db = FakeDb([folder], {folder: [f"{folder}/llt.asc"]})
    said = meddra.load_waiting(db, get=lambda name: LLT)
    assert "failed" in said
    status, message = db.status(folder)
    assert status == "failed" and "missing" in message
    assert "meddra_llt" not in db.copied


def test_a_database_error_never_reaches_the_public_log():
    folder = "uploads/20261110T080000Z"
    db = FakeDb([folder], {folder: [f"{folder}/x.zip"]})

    def broken(name):
        raise ValueError("Test sleeplessness")      # a message that could quote a term

    with pytest.raises(RuntimeError) as err:
        meddra.load_waiting(db, get=broken)
    assert "sleeplessness" not in str(err.value) and err.value.__cause__ is None
    assert db.status(folder)[0] == "failed"


def test_nothing_waiting_is_nothing_to_do():
    assert meddra.load_waiting(FakeDb([], {}), get=lambda n: b"") == "no upload is waiting"
