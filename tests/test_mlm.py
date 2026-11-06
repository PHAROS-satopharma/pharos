"""EMA's literature-monitoring list, on a trimmed copy of the real list (valid 1 June 2020)."""

from __future__ import annotations

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
