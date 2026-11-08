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


def _search(db, text: str) -> list[dict]:
    return db.fetchall("select source, code, name, found_as, status from term_search(%s, array['oae'])", (text,))


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
    path = db.fetchall("select code from term_path('oae', 'OAE_9100004') order by depth")
    assert [r["code"] for r in path] == ["OAE_9100001", "OAE_9100002", "OAE_9100004"]

    # A third release dropping a concept stages its retirement.
    third = _release("CI-3", [c for c in second.concepts.values() if c.code != "OAE_9100003"])
    assert "0 added, 0 changed, 1 retired" in base.load(db, third, min_concepts=1)
