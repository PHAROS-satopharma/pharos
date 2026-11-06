"""EMA's literature-monitoring list, on a trimmed copy of the real list (valid 1 June 2020)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from collectors import mlm

FIXTURE = Path(__file__).parent / "fixtures" / "mlm" / "mlm-2020-06-01-trimmed.xlsx"


def test_reads_the_substance_groups():
    rows = mlm.parse(FIXTURE.read_bytes())
    assert {"group_id": 3, "group_name": "IBUPROFEN", "substances": "IBUPROFEN"} in rows
    assert all(r["group_name"] != "VALERIANA" for r in rows), "the herbal sheet is left out"


def test_covered_and_not_covered():
    rows = mlm.parse(FIXTURE.read_bytes())
    got = mlm.match(rows, [{"id": "I", "inn_en": "Ibuprofen"}, {"id": "M", "inn_en": "meloxicam"},
                           {"id": "L", "inn_en": "lornoxicam"}, {"id": "A", "inn_en": "ascorbic acid"}])
    by = {g["ingredient_id"]: g for g in got}
    assert by["I"]["group_id"] == 3 and by["I"]["named_group"] is True
    assert by["M"]["group_name"] == "MELOXICAM"
    assert "L" not in by, "lornoxicam is not on EMA's list"
    assert "A" not in by, "appearing in a combination (ascorbic acid, ibuprofen) is not coverage"


def test_a_list_without_its_header_is_refused():
    import io

    import openpyxl
    import pytest

    wb = openpyxl.Workbook()
    wb.active.append(["Group", "Name"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ValueError):
        mlm.parse(buf.getvalue())


class WatchDb:
    """Enough of Db for refresh(): the active ingredients, mlm_entry, and the writes."""

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
            self.entries.append({"ingredient_id": params["ingredient_id"], "group_id": params["group_id"],
                                 "sha256": params["sha256"]})


IBUPROFEN = {"id": "I", "inn_en": "ibuprofen"}
MELOXICAM = {"id": "M", "inn_en": "meloxicam"}
PUT = lambda content, mime: (None, "raw/x")  # noqa: E731


def test_the_same_list_and_the_same_ingredients_store_nothing():
    db = WatchDb([IBUPROFEN])
    assert mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT) == 1
    db.writes.clear()
    assert mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT) is None
    assert db.writes == []


def test_an_ingredient_added_after_the_list_was_read_is_covered_from_the_same_list():
    # EMA rarely publishes a new list: an ingredient added in between read "not monitored by EMA", so its
    # literature cases looked like ours to report to EudraVigilance.
    db = WatchDb([IBUPROFEN])
    mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT)
    db.ingredients = [IBUPROFEN, MELOXICAM]
    assert mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT) == 2
    assert {e["ingredient_id"] for e in db.entries} == {"I", "M"}


def test_a_retired_ingredient_loses_its_row_without_waiting_for_a_new_list():
    db = WatchDb([IBUPROFEN, MELOXICAM])
    mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT)
    db.ingredients = [IBUPROFEN]
    assert mlm.refresh(db, FIXTURE.read_bytes(), "s1", "list.xlsx", PUT) == 1
    assert {e["ingredient_id"] for e in db.entries} == {"I"}


def test_the_list_is_read_every_day():
    import yaml

    steps = yaml.safe_load((Path(__file__).parents[1] / ".github" / "workflows" / "collect.yml").read_text(
        encoding="utf-8"))["jobs"]["collect"]["steps"]
    step = next(s for s in steps if s.get("name") == "Literature monitoring list")
    assert "'daily'" in step["if"]
