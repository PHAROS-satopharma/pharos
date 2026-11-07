"""PHAROS — the real SQL of the drug classes and the check of the past (``collectors.core.store.Store``, migration
0034) against a real Postgres. SKIPPED unless ``PHAROS_TEST_DB_URL`` is set: CI sets it to its own throw-away
Postgres 16 after applying the migrations; it must never point at the live project.

Each test uses rows of its own (a random suffix) and closes any check of the past it opens, so the tests run
against a database that already holds data.
"""

from __future__ import annotations

import os
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from collectors.core.models import SourceConfig
from collectors.core.store import Store

DB_URL = os.environ.get("PHAROS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="PHAROS_TEST_DB_URL is not set (CI only)")


@pytest.fixture(scope="module")
def db():
    from collectors.core.db import Db

    d = Db(DB_URL)
    yield d
    d.close()


@pytest.fixture()
def store(db):
    s = Store(db)
    s.db.execute("update rematch_job set finished_at = now() where finished_at is null")
    yield s
    s.db.execute("update rematch_job set finished_at = now() where finished_at is null")


@pytest.fixture()
def tag() -> str:
    return uuid.uuid4().hex[:10]


def _code() -> str:
    """A made-up ATC level-4 code, unlikely to meet another test's."""
    return "X" + "".join(random.choices(string.digits, k=2)) + "".join(random.choices(string.ascii_uppercase, k=2))


def _source(store: Store, tag: str, kind: str = "safety") -> str:
    reg = {"id": f"T-{tag}", "country_code": "SE", "country_name": "Sweden", "name": f"Test regulator {tag}",
           "languages": ["sv"], "homepage": None}
    store.upsert_regulator(reg)
    src = SourceConfig(id=f"t-{tag}-{kind}", regulator_id=reg["id"], kind=kind, channel="html",
                       url=f"https://example.test/{tag}", parser="generic_html", languages=["sv"], schedule="4h",
                       enabled=True, options={}, expected_max_gap_days=30)
    store.upsert_catalogue_source(src, None)
    return src.id


def _ingredient(store: Store, tag: str, atc: str | None = None) -> str:
    row = store.db.fetchone("insert into ingredient (inn_en, atc_code) values (%(n)s, %(a)s) returning id",
                            {"n": f"testoxacin-{tag}", "a": atc})
    return str(row["id"])


def _term(store: Store, ingredient_id: str, term: str, lang: str = "en") -> str:
    row = store.db.fetchone(
        """insert into ingredient_term (ingredient_id, lang, term) values (%(i)s, %(l)s, %(t)s) returning id""",
        {"i": ingredient_id, "l": lang, "t": term})
    return str(row["id"])


def test_a_class_is_made_once_and_never_changed(store, tag):
    code = _code() + "01"
    ing = _ingredient(store, tag, code)
    mine = [r for r in store.ingredients_for_classes() if r["id"] == ing]
    assert mine == [{"id": ing, "inn_en": f"testoxacin-{tag}", "atc_code": code, "class_codes": []}]
    words = [{"lang": "en", "term": "testoxacin", "mode": "stem", "source": "wikidata"},
             {"lang": "ja", "term": "テストキサシン", "mode": "substring", "source": "wikidata"}]
    cid = store.create_drug_class(code=code[:5], name_en="Testoxacins", wikidata_qid="Q1", terms=words)
    again = store.create_drug_class(code=code[:5], name_en="Changed", wikidata_qid="Q2",
                                    terms=[{"lang": "fr", "term": "autre", "mode": "stem", "source": "wikidata"}])
    assert again == cid and store.drug_class_id(code[:5]) == cid
    row = store.db.fetchone("select name_en, origin, wikidata_qid, confirmed_at from drug_class where id = %(c)s",
                            {"c": cid})
    assert row == {"name_en": "Testoxacins", "origin": "atc", "wikidata_qid": "Q1", "confirmed_at": None}
    terms = store.db.fetchall("""select lang, term, mode::text as mode, source, rematched_at from class_term
                                  where class_id = %(c)s order by lang""", {"c": cid})
    assert [(t["lang"], t["term"], t["mode"], t["source"]) for t in terms] == [
        ("en", "testoxacin", "stem", "wikidata"), ("ja", "テストキサシン", "substring", "wikidata")]
    assert all(t["rematched_at"] is None for t in terms)
    store.link_ingredient_class(ing, cid)
    store.link_ingredient_class(ing, cid)
    assert [r["class_codes"] for r in store.ingredients_for_classes() if r["id"] == ing] == [[code[:5]]]
    # the new class's words are due for the check of the past, now that a watched ingredient carries them
    ids = {str(r["id"]) for r in store.db.fetchall("select id from class_term where class_id = %(c)s", {"c": cid})}
    assert ids <= set(store.rematch_due_terms()[1])


def test_the_check_of_the_past_walks_the_notices_and_marks_the_words(store, tag):
    src = _source(store, tag)
    lit = _source(store, tag, "literature")
    ing = _ingredient(store, tag)
    t_new = _term(store, ing, f"testoxacin{tag}")
    t_late = _term(store, ing, f"brand{tag}")
    docs = []
    for k, (source, days) in enumerate(((src, 30), (src, 60), (src, 900), (lit, 30))):
        did = store.insert_document({
            "source_id": source, "external_id": f"{tag}-{k}", "url": f"https://example.test/{tag}/{k}",
            "title_orig": f"Notice {k}", "lang": "sv", "doc_type": "dhpc",
            "published_date": date.today() - timedelta(days=days), "sha256": None, "r2_key": f"raw/{tag}/shared",
            "mime": "text/html", "bytes": 10, "extraction": "html", "structured": None, "is_backfill": False})
        docs.append(did)
    store.insert_document_text(docs[0], None, f"testoxacin{tag} kept")
    att = store.insert_attachment({"document_id": docs[1], "url": f"https://example.test/{tag}.pdf", "filename": "a.pdf",
                                   "sha256": None, "r2_key": f"att/{tag}", "mime": "application/pdf", "bytes": 5,
                                   "extraction": "text", "words": 3})
    issue = store.create_issue(doc_type="dhpc", title="t", anchor_document_id=docs[0], first_date=date.today(),
                               class_only=True, is_backfill=False)
    store.link_document(issue, docs[0], link="anchor", method="auto", score=None)
    store.add_issue_ingredients(issue, [ing])
    store.insert_match({"document_id": docs[0], "attachment_id": None, "ingredient_id": ing, "class_id": None,
                        "term_id": t_new, "class_term_id": None, "field": "body", "start_offset": 0, "end_offset": 3,
                        "matched_text": "tes", "snippet": "", "confidence": "high"})

    due_i, _ = store.rematch_due_terms()
    assert {t_new, t_late} <= set(due_i)
    assert store.rematch_open_job() is None
    since = date.today() - timedelta(days=365)
    job = store.rematch_create_job(since=since, ingredient_term_ids=[t_new, t_late], class_term_ids=[], trigger="daily")
    assert store.rematch_open_job()["id"] == job["id"] and job["cursor_document_id"] is None
    terms = store.rematch_terms(job["ingredient_term_ids"], job["class_term_ids"])
    assert sorted(t.term for t in terms) == sorted([f"testoxacin{tag}", f"brand{tag}"])
    assert all(t.ingredient_id == ing and t.kind == "inn" for t in terms)

    before = datetime.now(timezone.utc) + timedelta(minutes=1)
    seen = [d for d in store.rematch_documents(since=since, before=before, after_id=None, limit=100000)
            if d["id"] in docs]
    assert [d["id"] for d in seen] == sorted(docs[:2])        # not 900 days old, not literature
    by_id = {d["id"]: d for d in seen}
    first, second = by_id[docs[0]], by_id[docs[1]]
    assert first["texts"] == [{"attachment_id": None, "text": f"testoxacin{tag} kept"}]
    assert first["matched_terms"] == {t_new} and first["issue"] == {"id": issue, "class_only": True, "ingredients": {ing}}
    assert first["country_code"] == "SE" and first["parser"] == "generic_html" and first["shared_original"] is True
    assert second["texts"] == [] and second["issue"] is None
    assert [(a["id"], a["r2_key"], a["extraction"]) for a in second["attachments"]] == [(att, f"att/{tag}", "text")]
    after = [d["id"] for d in store.rematch_documents(since=since, before=before, after_id=min(docs[:2]), limit=100000)]
    assert min(docs[:2]) not in after and max(docs[:2]) in after
    assert [d["id"] for d in store.rematch_documents(since=since, before=datetime(2000, 1, 1, tzinfo=timezone.utc),
                                                     after_id=None, limit=100000) if d["id"] in docs] == []

    store.rematch_advance(job["id"], cursor=docs[1], checked=2, reread=1, matched=1, issues_created=1)
    store.set_issue_names_ingredient(issue)
    assert store.db.fetchone("select class_only from issue where id = %(i)s", {"i": issue})["class_only"] is False
    # a word changed while the job runs stays due
    store.db.execute("update ingredient_term set term = term || 'x' where id = %(t)s", {"t": t_late})
    store.rematch_finish(job["id"])
    row = store.db.fetchone("select * from rematch_job where id = %(j)s", {"j": job["id"]})
    assert row["finished_at"] is not None and str(row["cursor_document_id"]) == docs[1]
    assert (row["documents_checked"], row["documents_reread"], row["documents_matched"], row["issues_created"]) == (2, 1, 1, 1)
    due_i, _ = store.rematch_due_terms()
    assert t_new not in due_i and t_late in due_i
    marked = store.db.fetchone("select rematched_at from ingredient_term where id = %(t)s", {"t": t_new})
    assert marked["rematched_at"] == row["started_at"]
    assert store.rematch_open_job() is None


def test_a_paused_ingredient_has_no_due_words(store, tag):
    ing = _ingredient(store, tag)
    t = _term(store, ing, f"paused{tag}")
    store.db.execute("update ingredient set active = false where id = %(i)s", {"i": ing})
    assert t not in store.rematch_due_terms()[0]
    store.db.execute("update ingredient_term set rematched_at = changed_at where id = %(t)s", {"t": t})
    store.db.execute("update ingredient set active = true where id = %(i)s", {"i": ing})
    # watching it again makes its words due again, though they were checked before
    assert t in store.rematch_due_terms()[0]


def test_a_parent_class_is_shown_but_not_searched_until_switched_on(store, tag):
    """Migration 0049: the link says what the class is and whether its words are searched; a link that exists is
    never changed; switching a class on makes its words due for the check of the past again."""
    code = _code()
    ing = _ingredient(store, tag, code + "01")
    group = store.create_drug_class(code=code, name_en=f"Group {tag}", wikidata_qid=None, terms=[
        {"lang": "en", "term": f"groupword{tag}", "mode": "stem", "source": "wikidata"}])
    parent = store.create_drug_class(code=code[:4], name_en=f"Parent {tag}", wikidata_qid=None, terms=[
        {"lang": "en", "term": f"parentword{tag}", "mode": "stem", "source": "wikidata"}])
    store.link_ingredient_class(ing, group)
    store.link_ingredient_class(ing, parent, relation="parent", enabled=False)
    # both switched into the literature (off by default since 0093), so enabled alone decides here
    store.db.execute("update ingredient_class set literature = true where ingredient_id = %(i)s", {"i": ing})
    links = store.db.fetchall(
        "select class_id, relation, enabled from ingredient_class where ingredient_id = %(i)s order by relation",
        {"i": ing})
    assert [(str(r["class_id"]), r["relation"], r["enabled"]) for r in links] == [
        (group, "group", True), (parent, "parent", False)]
    assert sorted(r["class_codes"] for r in store.ingredients_for_classes() if r["id"] == ing) == [[code, code[:4]]]
    # only the group's words are searched, in notices, in the literature and by the check of the past
    assert {t.term for t in store.load_terms() if t.class_id in (group, parent)} == {f"groupword{tag}"}
    assert store.class_words("en")[f"testoxacin-{tag}"] == [f"groupword{tag}"]
    assert ing in store.class_ingredients()[group] and parent not in store.class_ingredients()
    pword = str(store.db.fetchone("select id from class_term where class_id = %(c)s", {"c": parent})["id"])
    assert pword not in store.rematch_due_terms()[1]
    # the parent's word was checked long ago; switching the class on makes it due again, and searched
    store.db.execute("update class_term set changed_at = '2026-01-01', rematched_at = '2026-01-01' where id = %(t)s",
                     {"t": pword})
    store.db.execute("update ingredient_class set enabled = true where ingredient_id = %(i)s and class_id = %(c)s",
                     {"i": ing, "c": parent})
    assert pword in store.rematch_due_terms()[1]
    assert store.class_words("en")[f"testoxacin-{tag}"] == [f"groupword{tag}", f"parentword{tag}"]
    assert ing in store.class_ingredients()[parent]
    # linking again, even differently, changes nothing
    store.link_ingredient_class(ing, parent, relation="group", enabled=False)
    row = store.db.fetchone("select relation, enabled from ingredient_class where ingredient_id = %(i)s and class_id = %(c)s",
                            {"i": ing, "c": parent})
    assert row == {"relation": "parent", "enabled": True}


def test_a_class_kept_out_of_the_literature_is_searched_in_notices_only(store, tag):
    """Migration 0051: ingredient_class.literature takes the class's words out of class_words (the PubMed and
    PMC watch) and leaves them in load_terms (notices). Every link starts out of the literature since 0093 (the
    literature is searched for the ingredients' names) until an administrator switches it on."""
    code = _code()
    ing = _ingredient(store, tag, code + "01")
    group = store.create_drug_class(code=code, name_en=f"Group {tag}", wikidata_qid=None, terms=[
        {"lang": "en", "term": f"litword{tag}", "mode": "stem", "source": "wikidata"}])
    store.link_ingredient_class(ing, group)
    row = store.db.fetchone("select literature from ingredient_class where ingredient_id = %(i)s and class_id = %(c)s",
                            {"i": ing, "c": group})
    assert row == {"literature": False}
    assert f"testoxacin-{tag}" not in store.class_words("en")
    store.db.execute("update ingredient_class set literature = true where ingredient_id = %(i)s and class_id = %(c)s",
                     {"i": ing, "c": group})
    assert store.class_words("en")[f"testoxacin-{tag}"] == [f"litword{tag}"]
    store.db.execute("update ingredient_class set literature = false where ingredient_id = %(i)s and class_id = %(c)s",
                     {"i": ing, "c": group})
    assert f"testoxacin-{tag}" not in store.class_words("en")
    assert f"litword{tag}" in {t.term for t in store.load_terms() if t.class_id == group}
    assert ing in store.class_ingredients()[group]
