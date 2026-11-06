"""PHAROS — which papers the daily open-access step asks for, against a real Postgres (collectors/fulltext.py).

The queries decide the 30-day re-ask and the one-year window in SQL, so they are run on the migrated schema.
SKIPPED unless ``PHAROS_TEST_DB_URL`` is set (CI only; see tests/test_store_pg.py)."""

from __future__ import annotations

import json
import os
import uuid

import pytest

from collectors import fulltext

DB_URL = os.environ.get("PHAROS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="PHAROS_TEST_DB_URL is not set (CI only)")


@pytest.fixture(scope="module")
def db():
    from collectors.core.db import Db

    d = Db(DB_URL)
    yield d
    d.close()


def _papers(db, tag: str) -> dict[str, str]:
    """A literature source of this test's own and its papers, by name -> document id."""
    db.execute("""insert into regulator (id, country_code, country_name, name, languages)
                  values (%(r)s, 'XN', 'CI Paperland', %(n)s, '{en}')""", {"r": f"T-OA-{tag}", "n": f"Library {tag}"})
    db.execute("""insert into source (id, regulator_id, kind, channel, url, parser, languages)
                  values (%(s)s, %(r)s, 'literature', 'api', 'https://eutils.example.test/', 'pubmed', '{en}')""",
               {"s": f"t-oa-{tag}", "r": f"T-OA-{tag}"})
    papers = {
        # name: (days since first seen, structured)
        "new": (2, {"pmid": "1", "doi": "10.1000/new"}),
        "no-doi": (2, {"pmid": "2", "doi": None}),
        "open": (2, {"pmid": "3", "doi": "10.1000/open", "oa": {"is_oa": True, "checked": "2025-12-01T00:00:00+00:00"}}),
        "closed-recent": (2, {"pmid": "4", "doi": "10.1000/closed-recent"}),
        "closed-old": (2, {"pmid": "5", "doi": "10.1000/closed-old"}),
        "too-old": (400, {"pmid": "6", "doi": "10.1000/too-old"}),
        "doi-asked": (2, {"pmid": "7", "doi": None}),
    }
    ids = {}
    for name, (days, structured) in papers.items():
        row = db.fetchone(
            """insert into document (source_id, external_id, url, title_orig, lang, doc_type, first_seen_at, structured)
               values (%(s)s, %(e)s, 'https://pubmed.example.test/', 'A paper', 'en', 'literature',
                       now() - make_interval(days => %(d)s), %(j)s::jsonb)
               returning id::text as id""",
            {"s": f"t-oa-{tag}", "e": f"{tag}-{name}", "d": days, "j": json.dumps(structured)})
        ids[name] = row["id"]
    # asked 5 days ago without an open copy; asked 31 days ago without one; a DOI asked for 5 days ago
    db.execute("""update document set structured = structured || jsonb_build_object('oa', jsonb_build_object(
                    'is_oa', false, 'known', true, 'checked', now() - interval '5 days')) where id = %(i)s::uuid""",
               {"i": ids["closed-recent"]})
    db.execute("""update document set structured = structured || jsonb_build_object('oa', jsonb_build_object(
                    'is_oa', false, 'known', true, 'checked', now() - interval '31 days')) where id = %(i)s::uuid""",
               {"i": ids["closed-old"]})
    db.execute("""update document set structured = structured || jsonb_build_object('doi_checked',
                    now() - interval '5 days') where id = %(i)s::uuid""", {"i": ids["doi-asked"]})
    return ids


def _waiting(db, sql: str, ids: dict[str, str]) -> set[str]:
    rows = db.fetchall(sql, {"age": fulltext.MAX_AGE_DAYS, "recheck": fulltext.RECHECK_DAYS, "limit": 100000})
    names = {v: k for k, v in ids.items()}
    return {names[r["id"]] for r in rows if r["id"] in names}


def test_the_daily_step_asks_each_paper_once_and_a_closed_one_again_after_30_days(db):
    ids = _papers(db, uuid.uuid4().hex[:10])
    assert _waiting(db, fulltext.PENDING_SQL, ids) == {"new", "closed-old"}
    assert _waiting(db, fulltext.DOI_PENDING_SQL, ids) == {"no-doi"}

    # what the run stores: asked now, no open copy; and a DOI found
    db.execute(fulltext.STORE_SQL, {"id": ids["new"], "oa": json.dumps({"is_oa": False, "known": True})})
    db.execute(fulltext.DOI_STORE_SQL, {"id": ids["no-doi"], "doi": "10.1000/found"})
    db.execute(fulltext.DOI_STORE_SQL, {"id": ids["doi-asked"], "doi": None})
    assert _waiting(db, fulltext.PENDING_SQL, ids) == {"closed-old", "no-doi"}
    assert _waiting(db, fulltext.DOI_PENDING_SQL, ids) == set()
    got = db.fetchone("select structured from document where id = %(i)s::uuid", {"i": ids["new"]})["structured"]
    assert got["oa"]["is_oa"] is False and fulltext.due(got["oa"]) is False and got["pmid"] == "1"
    got = db.fetchone("select structured from document where id = %(i)s::uuid", {"i": ids["doi-asked"]})["structured"]
    assert got["doi"] is None and "doi_checked" in got
