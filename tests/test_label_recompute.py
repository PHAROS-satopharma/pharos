"""The gap between our label and a label change is written to ``label_gap`` when the change is recorded, and
caught up on every run for the changes of the last year that have no row for the current version of our label
(a new version of our label re-compares everything). No database: a fake answers the two queries."""

from __future__ import annotations

from collectors.labels import recompute

CHANGE_1 = "00000000-0000-0000-0000-00000043c001"
CHANGE_2 = "00000000-0000-0000-0000-00000043c002"
LABEL_EN = "00000000-0000-0000-0000-00000043ab01"
LABEL_AR = "00000000-0000-0000-0000-00000043ab02"
DIFF = [{"section": "4.4", "before": "Use with caution in renal impairment.",
         "after": "Use with caution in renal impairment. Cases of acute kidney injury have been reported.",
         "changes": []}]
OURS = {"4.4": "Use with caution in patients with renal impairment. Cases of acute kidney injury have been reported rarely."}


class FakeDb:
    def __init__(self, rows: list[dict] | None = None, labels: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.labels = labels or []
        self.sql: list[tuple[str, dict]] = []
        self.written: list[dict] = []

    def fetchall(self, sql, params=None):
        self.sql.append((sql, dict(params or {})))
        if "from our_label" in sql and "spc_change" not in sql:
            return [dict(r) for r in self.labels]
        return [dict(r) for r in self.rows]

    def execute(self, sql, params=None):
        self.sql.append((sql, dict(params or {})))
        assert "insert into label_gap" in sql
        self.written.append(dict(params))


def _gap(written: dict) -> dict:
    """The gap as stored: a psycopg Jsonb wrapper (.obj) with psycopg, a JSON string without it."""
    import json

    g = getattr(written["g"], "obj", written["g"])
    return json.loads(g) if isinstance(g, str) else g


def test_recompute_writes_a_gap_for_every_change_and_label_without_one():
    db = FakeDb(rows=[
        {"change_id": CHANGE_1, "diff": DIFF, "label_id": LABEL_EN, "our_lang": "en", "our_sections": OURS,
         "their_lang": "en"},
        {"change_id": CHANGE_2, "diff": DIFF, "label_id": LABEL_AR, "our_lang": "ar", "our_sections": {"4.4": "x"},
         "their_lang": "en"},
    ])
    assert recompute.recompute_gaps(db) == 2
    assert [w["c"] for w in db.written] == [CHANGE_1, CHANGE_2]
    assert [w["l"] for w in db.written] == [LABEL_EN, LABEL_AR]
    first, second = (_gap(w) for w in db.written)
    assert first["lang_match"] is True and first["covered"] == 1
    assert second["lang_match"] is False and second["sections"] == []       # never compared across languages


def test_recompute_asks_only_for_the_last_year_against_current_labels_lacking_a_row():
    db = FakeDb()
    assert recompute.recompute_gaps(db) == 0
    sql, params = db.sql[0]
    q = " ".join(sql.split()).lower()
    assert "superseded_at is null" in q, "only the current version of our label"
    assert "not exists" in q and "label_gap" in q, "only the pairs with no gap yet"
    assert params["days"] == 365
    assert "order by sc.created_at desc" in q
    assert not db.written


def test_recompute_takes_the_days_and_the_limit():
    db = FakeDb()
    recompute.recompute_gaps(db, days=30, limit=10)
    _, params = db.sql[0]
    assert params == {"days": 30, "limit": 10}


def test_the_write_is_an_upsert_per_change_and_label():
    q = " ".join(recompute.WRITE_SQL.split()).lower()
    assert "on conflict (spc_change_id, our_label_id) do update" in q
    assert "computed_at = now()" in q


def test_gap_for_change_compares_with_every_current_label_of_the_ingredient():
    db = FakeDb(labels=[{"id": LABEL_EN, "lang": "en", "sections": OURS},
                        {"id": LABEL_AR, "lang": "ar", "sections": {"4.4": "x"}}])
    n = recompute.gap_for_change(db, CHANGE_1, "00000000-0000-0000-0000-00000043a001", DIFF, "en-GB")
    assert n == 2
    sql, params = db.sql[0]
    assert "superseded_at is null" in sql and params == {"i": "00000000-0000-0000-0000-00000043a001"}
    assert [w["l"] for w in db.written] == [LABEL_EN, LABEL_AR]
    assert _gap(db.written[0])["their_lang"] == "en-GB" and _gap(db.written[0])["lang_match"] is True
    assert _gap(db.written[1])["lang_match"] is False


def test_gap_for_change_writes_nothing_without_a_label_of_ours():
    db = FakeDb()
    assert recompute.gap_for_change(db, CHANGE_1, "ing", DIFF, "en") == 0
    assert not db.written


def test_gap_for_change_reads_a_diff_stored_as_a_json_string():
    import json

    db = FakeDb(labels=[{"id": LABEL_EN, "lang": "en", "sections": json.dumps(OURS)}])
    assert recompute.gap_for_change(db, CHANGE_1, "ing", json.dumps(DIFF), "en") == 1
    assert _gap(db.written[0])["covered"] == 1
