"""PHAROS — the terminology loader against a real Postgres (migration 0103): first release applied, the next one
staged, then activated by an administrator, and the search finds what was activated.

SKIPPED unless ``PHAROS_TEST_DB_URL`` is set (CI only; see tests/test_store_pg.py). Every code and name is invented.
"""

from __future__ import annotations

import os

import pytest

from collectors.coding.terminology import base

DB_URL = os.environ.get("PHAROS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="PHAROS_TEST_DB_URL is not set (CI only)")
ADMIN = "00000000-0000-0000-0000-0000000000a1"


@pytest.fixture()
def db():
    from collectors.core.db import Db

    d = Db(DB_URL)
    d.execute("delete from term_change where source = 'oae'")
    d.execute("delete from term_concept where source = 'oae'")
    d.execute("delete from term_release where source = 'oae'")
    yield d
    d.execute("delete from term_change where source = 'oae'")
    d.execute("delete from term_concept where source = 'oae'")
    d.execute("delete from term_release where source = 'oae'")
    d.close()


def _release(version: str, concepts: list[base.Concept], data: bytes | None = None) -> base.Release:
    return base.Release(source="oae", version=version, url="https://example.test/oae.owl",
                        data=data or version.encode() + repr(sorted(c.code for c in concepts)).encode(),
                        concepts={c.code: c for c in concepts}, mime="application/rdf+xml")


READER = "00000000-0000-0000-0000-0000000000b2"


def _read(db, sql: str, params: tuple) -> list[dict]:
    """As the screen reads: signed in as a PHAROS person (0105: nobody else finds anything)."""
    db.execute("select set_config('request.jwt.claims', %s, false)",
               ('{"sub": "%s", "role": "authenticated"}' % READER,))
    try:
        return db.fetchall(sql, params)
    finally:
        db.execute("select set_config('request.jwt.claims', '', false)")


def _search(db, text: str) -> list[dict]:
    return _read(db, "select source, code, name, found_as, status from term_search(%s, array['oae'])", (text,))


def test_first_applied_then_staged_then_activated(db):
    first = _release("CI-1", [
        base.Concept(code="OAE_9100001", name="test adverse event"),
        base.Concept(code="OAE_9100002", name="test insomnia AE", names=[("test sleeplessness", "en", False)],
                     parents=["OAE_9100001"]),
        base.Concept(code="OAE_9100003", name="test itch AE", parents=["OAE_9100001"]),
    ])
    assert "loaded (the first release)" in base.load(db, first, min_concepts=1)
    assert [r["code"] for r in _search(db, "test sleeplessness")][:1] == ["OAE_9100002"]
    assert db.fetchone("select status from term_release where source = 'oae'")["status"] == "active"

    # The same file again is nothing to do.
    assert "seen already" in base.load(db, _release("CI-1", list(first.concepts.values()), first.data),
                                       min_concepts=1)

    second = _release("CI-2", [
        base.Concept(code="OAE_9100001", name="test adverse event"),
        base.Concept(code="OAE_9100002", name="test insomnia AE", names=[("test wakefulness", "en", False)],
                     parents=["OAE_9100001"]),
        base.Concept(code="OAE_9100003", name="test itch AE", parents=["OAE_9100001"]),
        base.Concept(code="OAE_9100004", name="test nightmare AE", parents=["OAE_9100002"]),
    ])
    said = base.load(db, second, min_concepts=1)
    assert "1 added, 1 changed, 0 retired" in said
    assert "OAE_9100004" not in [r["code"] for r in _search(db, "test nightmare AE")]   # staged: not yet
    staged = db.fetchone("select id from term_release where source = 'oae' and status = 'staged'")["id"]

    db.execute("select set_config('request.jwt.claims', %s, false)",
               ('{"sub": "%s", "role": "authenticated"}' % ADMIN,))
    db.execute("select activate_term_release(%s)", (staged,))
    db.execute("select set_config('request.jwt.claims', '', false)")
    assert [r["code"] for r in _search(db, "test nightmare AE")][:1] == ["OAE_9100004"]
    assert [r["code"] for r in _search(db, "test wakefulness")][:1] == ["OAE_9100002"]
    assert not [r for r in _search(db, "test sleeplessness") if r["found_as"] == "test sleeplessness"]
    path = _read(db, "select code from term_path(%s, %s) order by depth", ("oae", "OAE_9100004"))
    assert [r["code"] for r in path] == ["OAE_9100001", "OAE_9100002", "OAE_9100004"]

    # A third release dropping a concept stages its retirement.
    third = _release("CI-3", [c for c in second.concepts.values() if c.code != "OAE_9100003"])
    assert "0 added, 0 changed, 1 retired" in base.load(db, third, min_concepts=1)



LOGGED = ["test logged rash", "qqzzxv wwyyk"]     # the second shares no letters' trigrams with any test concept


def _logged(db, sql: str) -> list[dict]:
    return db.fetchall(sql + " where text = any(%s) order by id", (LOGGED,))


def test_every_search_is_logged_and_only_admins_read_the_log(db):
    first = _release("CI-LOG", [base.Concept(code="OAE_9200001", name="test logged rash AE")])
    assert "loaded (the first release)" in base.load(db, first, min_concepts=1)
    db.execute("delete from term_search_log where text = any(%s)", (LOGGED,))
    try:
        hits = _read(db, "select code from term_find(%s, array['oae'], 12, 'proposal')", (LOGGED[0],))
        assert [r["code"] for r in hits][:1] == ["OAE_9200001"]          # the same answers as term_search()
        assert _read(db, "select code from term_find(%s, array['oae'])", (LOGGED[1],)) == []

        rows = _logged(db, "select person_id::text as person_id, place, results, sources from term_search_log")
        reader = db.fetchone("select id::text as id from person where auth_user_id = %s", (READER,))["id"]
        assert [(r["person_id"], r["place"], r["sources"]) for r in rows] == [
            (reader, "proposal", ["oae"]), (reader, "typed", ["oae"])]
        assert rows[0]["results"] >= 1 and rows[1]["results"] == 0

        # Someone who is not a PHAROS person finds nothing and leaves no row.
        db.execute("select set_config('request.jwt.claims', %s, false)",
                   ('{"sub": "00000000-0000-0000-0000-00000000ffff", "role": "authenticated"}',))
        try:
            assert db.fetchall("select code from term_find(%s)", (LOGGED[0],)) == []
        finally:
            db.execute("select set_config('request.jwt.claims', '', false)")
        assert len(_logged(db, "select id from term_search_log")) == 2

        # A reader gets no counts; an administrator gets today's, by person and place.
        assert _read(db, "select * from term_search_counts(%s)", (None,)) == []
        db.execute("select set_config('request.jwt.claims', %s, false)",
                   ('{"sub": "%s", "role": "authenticated"}' % ADMIN,))
        try:
            counts = db.fetchall("select place, searches, found_nothing from term_search_counts() "
                                 "where person = %s order by place", ("CI Reader",))
        finally:
            db.execute("select set_config('request.jwt.claims', '', false)")
        assert [(c["place"], c["searches"], c["found_nothing"]) for c in counts] == [
            ("proposal", 1, 0), ("typed", 1, 1)]
    finally:
        db.execute("delete from term_search_log where text = any(%s)", (LOGGED,))
