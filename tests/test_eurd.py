"""The EURD list reader on a trimmed copy of the real list (EMA/630645/2012 Rev.165, 21 October 2026)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from collectors import eurd

FIXTURE = Path(__file__).parent / "fixtures" / "eurd" / "eurd-2026-10-21-trimmed.xlsx"


@pytest.fixture(scope="module")
def parsed():
    return eurd.parse(FIXTURE.read_bytes())


def test_header_and_version(parsed):
    meta, rows = parsed
    assert meta["version"] and meta["version"].startswith("EMA/630645/2012")
    assert rows and all(isinstance(r["eurd_id"], int) for r in rows)


def test_lornoxicam_row(parsed):
    _, rows = parsed
    (lorn,) = [r for r in rows if r["eurd_id"] == 1911]
    assert lorn["substance"] == "lornoxicam"
    assert lorn["frequency"] == "7 years"
    assert lorn["dlp"] == date(2031, 12, 1)
    assert lorn["submission_date"] == date(2032, 2, 29)
    assert lorn["generics_psur_required"] is False
    assert lorn["procedure"] == "PSUSA/00001911/203112"
    assert lorn["lead_ms"] == "Spain"


def test_whole_word_and_combinations(parsed):
    _, rows = parsed
    ings = [{"id": "L", "inn_en": "Lornoxicam"}, {"id": "I", "inn_en": "ibuprofen"}]
    got = eurd.match(rows, ings)
    lorn = [m for m in got if m["ingredient_id"] == "L"]
    assert [m["eurd_id"] for m in lorn] == [1911] and lorn[0]["combination"] is False
    ibu = [m for m in got if m["ingredient_id"] == "I"]
    assert ibu, "ibuprofen has rows in the list"
    assert any(m["combination"] for m in ibu), "ibuprofen combinations are kept and flagged"
    assert not any("dexibuprofen" in m["substance"].lower() and "/" not in m["substance"] for m in ibu)


def test_an_exclusion_is_not_a_match():
    rows = [{"eurd_id": 1601, "substance": "deanol and all combinations with deanol except for diclofenac"},
            {"eurd_id": 1048, "substance": "diclofenac (systemic formulations)"}]
    got = eurd.match(rows, [{"id": "D", "inn_en": "diclofenac"}])
    assert [m["eurd_id"] for m in got] == [1048]


def test_day_cells():
    assert eurd._day("01/12/2031") == date(2031, 12, 1)
    assert eurd._day("Not available*") is None
    assert eurd._day("31/02/2031") is None
    assert eurd._day(None) is None


def test_store_replaces_in_one_transaction():
    class FakeDb:
        def __init__(self):
            self.sql: list[str] = []
            self.depth = 0

        @contextmanager
        def transaction(self):
            self.depth += 1
            yield self
            self.depth -= 1

        def execute(self, sql, params=None):
            assert self.depth == 1, "every write is inside the transaction"
            self.sql.append(sql.split()[0])

    db = FakeDb()
    row = {k: None for k in eurd.COLUMNS} | {"eurd_id": 1911, "substance": "lornoxicam",
                                              "ingredient_id": "L", "combination": False}
    n = eurd.store(db, {"version": "v", "list_date": None}, [row], sha="ab", r2_key="raw/ab")
    assert n == 1 and db.sql == ["delete", "insert"]


class WatchDb:
    """Enough of Db for refresh(): the active ingredients, eurd_entry, and the writes."""

    def __init__(self, ingredients, entries=()):
        self.ingredients = list(ingredients)
        self.entries = list(entries)
        self.writes: list[str] = []

    @contextmanager
    def transaction(self):
        yield self

    def fetchall(self, sql, params=None):
        return self.ingredients if "from ingredient" in sql else self.entries

    def execute(self, sql, params=None):
        self.writes.append(sql.split()[0])
        if sql.split()[0] == "delete":
            self.entries = []
        else:
            self.entries.append({"eurd_id": params["eurd_id"], "ingredient_id": params["ingredient_id"],
                                 "sha256": params["sha256"]})


LORNOXICAM = {"id": "L", "inn_en": "lornoxicam"}
MELOXICAM = {"id": "M", "inn_en": "meloxicam"}
PUT = lambda content, mime: (None, "raw/x")  # noqa: E731


def test_the_same_list_and_the_same_ingredients_store_nothing():
    content = FIXTURE.read_bytes()
    db = WatchDb([LORNOXICAM])
    assert eurd.refresh(db, content, "s1", PUT) >= 1
    db.writes.clear()
    assert eurd.refresh(db, content, "s1", PUT) is None
    assert db.writes == []


def test_an_ingredient_added_after_the_list_was_read_gets_its_rows_from_the_same_list():
    # EMA republishes about monthly: an ingredient added in between waited for the next list, and its
    # readiness said "not on the EURD list" although the list held its row.
    content = FIXTURE.read_bytes()
    db = WatchDb([MELOXICAM])
    eurd.refresh(db, content, "s1", PUT)
    assert {e["eurd_id"] for e in db.entries} == {10474}
    db.ingredients = [MELOXICAM, LORNOXICAM]
    assert eurd.refresh(db, content, "s1", PUT) == 2
    assert {(e["eurd_id"], e["ingredient_id"]) for e in db.entries} == {(10474, "M"), (1911, "L")}


def test_a_retired_ingredient_loses_its_rows_without_waiting_for_a_new_list():
    content = FIXTURE.read_bytes()
    db = WatchDb([MELOXICAM, LORNOXICAM])
    eurd.refresh(db, content, "s1", PUT)
    db.ingredients = [MELOXICAM]
    assert eurd.refresh(db, content, "s1", PUT) == 1
    assert {e["ingredient_id"] for e in db.entries} == {"M"}
