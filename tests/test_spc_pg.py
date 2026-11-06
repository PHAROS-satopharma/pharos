"""PHAROS — the label watch against a real Postgres: a failed gap check never loses the change it describes.

The other label-watch tests use a fake database, which cannot show what Postgres does after an error inside a
transaction: everything after it is refused, and the transaction is rolled back. SKIPPED unless
``PHAROS_TEST_DB_URL`` is set (CI only; see tests/test_store_pg.py).
"""

from __future__ import annotations

import os
import uuid

import pytest

from collectors.core.store import Store
from collectors.spc.run import watch_product
from tests.fakes_a2 import FakeCtx
from tests.test_spc import _Module, _snap
from tests.test_store_pg import _ingredient, _source

DB_URL = os.environ.get("PHAROS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="PHAROS_TEST_DB_URL is not set (CI only)")


@pytest.fixture(scope="module")
def db():
    from collectors.core.db import Db

    d = Db(DB_URL)
    yield d
    d.close()


def test_a_database_error_in_the_gap_check_never_loses_the_change(db, monkeypatch):
    # 6 Nov 2026 (finding 10 of the review of #119): the check ran inside the change's transaction with no
    # savepoint; a database error there was logged and swallowed, and the change, its issue and its snapshot
    # were rolled back with it.
    from collectors.labels import recompute

    store, tag = Store(db), uuid.uuid4().hex[:10]
    src = _source(store, tag)
    ing = _ingredient(store, tag)
    product = db.fetchone(
        """insert into spc_product (ingredient_id, source_id, country_code, national_id, product_name)
           values (%(i)s, %(s)s, 'ES', %(n)s, %(p)s)
           returning id::text as id, national_id, product_name, mah, country_code, url""",
        {"i": ing, "s": src.id, "n": f"N-{tag}", "p": f"TESTAMINE {tag} 8 MG"})

    def broken(conn, *a, **k):
        conn.execute("select 1 / 0")      # any database error inside the check

    monkeypatch.setattr(recompute, "gap_for_change", broken)
    base = "Testamine reduce la agregación plaquetaria."
    module = _Module(_snap(base), _snap(base + " Riesgo de lesión hepática."))
    ctx = FakeCtx()
    watch_product(db, ctx, module, src.id, product, {"id": ing, "inn_en": f"testamine-{tag}"})
    issue_id = watch_product(db, ctx, module, src.id, product, {"id": ing, "inn_en": f"testamine-{tag}"})

    p = {"p": product["id"]}
    assert issue_id is not None
    assert db.fetchone("select count(*) as n from spc_snapshot where spc_product_id = %(p)s", p)["n"] == 2
    change = db.fetchone("select issue_id::text as issue_id from spc_change where spc_product_id = %(p)s", p)
    assert change is not None and change["issue_id"] == issue_id
    assert db.fetchone("select count(*) as n from issue where id = %(i)s", {"i": issue_id})["n"] == 1
