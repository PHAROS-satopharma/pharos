"""EMA's herbal list, read and stored (11 November 2026: ivy leaf could not be added)."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from collectors import herbal


def _rows(n: int) -> list[dict]:
    return [{"category": "Human", "english_common_name": f"Herb {i} leaf", "latin_name": f"Herbae {i} folium",
             "botanical_name": f"Herba number{i} L.", "combination": "No"} for i in range(n)]


def test_parse_keeps_single_human_herbs_once():
    data = {"data": [
        {"category": "Human", "english_common_name": "Ivy leaf", "latin_name": "Hederae helicis folium",
         "botanical_name": "Hedera helix L.", "combination": "No"},
        {"category": "Human", "english_common_name": "ivy leaf", "latin_name": "Hederae helicis folium",
         "botanical_name": "Hedera helix L.", "combination": "No"},
        {"category": "Human", "english_common_name": "Thyme / Primula root", "latin_name": "x",
         "combination": "Yes"},
        {"category": "Veterinary", "english_common_name": "Horse herb", "latin_name": "Equi herba"},
        {"category": "Human", "english_common_name": "No latin", "latin_name": ""},
        "not a row",
    ]}
    rows = herbal.parse(json.dumps(data).encode())
    assert rows == [{"name": "Ivy leaf", "latin": "Hederae helicis folium", "botanical": "Hedera helix L."}]


def test_parse_of_something_that_is_not_the_list():
    assert herbal.parse(b"[]") == []
    assert herbal.parse(b'{"data": null}') == []
    with pytest.raises(ValueError):
        herbal.parse(b"<html>Too Many Requests</html>")


class FakeDb:
    def __init__(self):
        self.sql: list[str] = []
        self.in_tx = False

    @contextmanager
    def transaction(self):
        self.in_tx = True
        try:
            yield self
        finally:
            self.in_tx = False

    def execute(self, sql, params=None):
        assert self.in_tx, "every write is inside the one transaction"
        self.sql.append(sql)


def test_store_replaces_the_list_in_one_transaction():
    db = FakeDb()
    assert herbal.store(db, herbal.parse(json.dumps({"data": _rows(60)}).encode())) == 60
    assert db.sql[0] == "delete from herbal_substance"
    assert len(db.sql) == 61


def test_a_short_list_is_never_stored():
    db = FakeDb()
    with pytest.raises(ValueError):
        herbal.store(db, herbal.parse(json.dumps({"data": _rows(3)}).encode()))
    assert db.sql == []
