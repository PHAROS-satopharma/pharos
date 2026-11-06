"""PHAROS — the real SQL in ``collectors.core.store.Store`` against a real Postgres.

Every other test uses ``MemoryStore``; this module runs the actual statements (ON CONFLICT targets,
enum casts, NUL cleaning, ``greatest``/``case`` updates, ordering) against a database that has every
migration applied. It is SKIPPED unless ``PHAROS_TEST_DB_URL`` is set — CI sets it to its own
throw-away Postgres 16 after applying the migrations; it must never point at the live project.

Each test uses its own regulator / source / people (a random suffix), so tests never see each
other's rows and can run against a database that already holds data.
"""

from __future__ import annotations

import os
import random
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
def store(db) -> Store:
    return Store(db)


@pytest.fixture()
def tag() -> str:
    return uuid.uuid4().hex[:10]


def _source(store: Store, tag: str) -> SourceConfig:
    """A regulator and a catalogue source of this test's own."""
    reg = {"id": f"T-{tag}", "country_code": "FI", "country_name": "Finland",
           "name": f"Test regulator {tag}", "languages": ["fi"], "homepage": None}
    store.upsert_regulator(reg)
    src = SourceConfig(id=f"t-{tag}", regulator_id=reg["id"], kind="safety", channel="html",
                       url=f"https://example.test/{tag}", parser="generic_html", languages=["fi"],
                       schedule="4h", enabled=True, options={}, expected_max_gap_days=30)
    store.upsert_catalogue_source(src, "first notes")
    return src


def _doc(source_id: str, external_id: str, **extra) -> dict:
    return {"source_id": source_id, "external_id": external_id,
            "url": f"https://example.test/{external_id}", "title_orig": f"Title {external_id}",
            "lang": "fi", "doc_type": "dhpc", "published_date": None, "sha256": None,
            "r2_key": None, "mime": "text/html", "bytes": 10, "extraction": "html",
            "structured": None, "is_backfill": False, **extra}


def _ingredient(store: Store, tag: str) -> str:
    row = store.db.fetchone("insert into ingredient (inn_en) values (%(n)s) returning id",
                            {"n": f"testamine-{tag}"})
    return str(row["id"])


def _person(store: Store, tag: str, name: str, *, role: str = "reviewer", active: bool = True,
            chat: bool = True) -> str:
    row = store.db.fetchone(
        """insert into person (full_name, email, role, active, telegram_chat_id)
           values (%(n)s, %(e)s, %(r)s, %(a)s, %(c)s) returning id""",
        {"n": f"{name} {tag}", "e": f"{name.lower()}-{tag}@example.test", "r": role, "a": active,
         "c": random.randint(10**12, 10**15) if chat else None})
    return str(row["id"])


# ───────────────────────────── settings, catalogue ─────────────────────────────


def test_settings_decode_jsonb(store):
    s = store.settings()
    assert isinstance(s["telegram_dry_run"], bool)
    assert isinstance(s["digest_hour_cairo"], int)


def test_catalogue_sync_refreshes_catalogue_rows_only(store, tag):
    src = _source(store, tag)
    row = store.get_source(src.id)
    assert row["origin"] == "catalogue" and row["notes"] == "first notes"
    assert store.country_code(src.regulator_id) == "FI"
    store.db.execute("update source set enabled = false where id = %(i)s", {"i": src.id})
    store.upsert_catalogue_source(src, "second notes")
    row = store.get_source(src.id)
    assert row["notes"] == "second notes"
    assert row["enabled"] is False                     # switching a source off is an admin's call
    store.db.execute("update source set origin = 'user', notes = 'mine' where id = %(i)s",
                     {"i": src.id})
    store.upsert_catalogue_source(src, "third notes")
    assert store.get_source(src.id)["notes"] == "mine"  # a person's row is never touched
    assert any(r["id"] == src.id for r in store.list_sources())


def test_catalogue_sync_writes_the_page_a_person_opens(store, tag):
    src = _source(store, tag)
    assert store.get_source(src.id)["page_url"] is None
    src.page_url = f"https://example.test/{tag}/news"
    store.upsert_catalogue_source(src, "notes")
    assert store.get_source(src.id)["page_url"] == f"https://example.test/{tag}/news"


# ───────────────────────────── runs ─────────────────────────────


def test_runs_and_source_runs(store, tag):
    src = _source(store, tag)
    run_id = store.create_run("manual", "test-sha")
    sr_id = store.start_source_run(run_id, src.id)
    store.finish_source_run(sr_id, http_status=200, items_seen=5, items_new=2, items_matched=1,
                            error=None, duration_ms=1234)
    store.finish_run(run_id, True)
    run = store.db.fetchone("select * from run where id = %(i)s", {"i": run_id})
    assert run["ok"] is True and run["finished_at"] is not None and run["git_sha"] == "test-sha"
    assert run["trigger"] == "manual"
    sr = store.db.fetchone("select * from source_run where id = %(i)s", {"i": sr_id})
    assert str(sr["run_id"]) == run_id and sr["source_id"] == src.id
    assert (sr["http_status"], sr["items_seen"], sr["items_new"], sr["items_matched"],
            sr["duration_ms"], sr["error"]) == (200, 5, 2, 1, 1234, None)
    assert sr["finished_at"] is not None


def test_source_state_sets_last_ok_only_when_ok(store, tag):
    src = _source(store, tag)
    store.set_source_state(src.id, health="degraded", consecutive_failures=1, ok=False)
    row = store.get_source(src.id)
    assert (row["health"], row["consecutive_failures"], row["last_ok_at"]) == ("degraded", 1, None)

    t1 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    store.set_source_state(src.id, health="ok", consecutive_failures=0, ok=True, last_item_at=t1)
    row = store.get_source(src.id)
    ok_at = row["last_ok_at"]
    assert row["health"] == "ok" and ok_at is not None and row["last_item_at"] == t1

    store.set_source_state(src.id, health="down", consecutive_failures=3, ok=False,
                           last_item_at=t1 - timedelta(days=5))
    row = store.get_source(src.id)
    assert row["health"] == "down" and row["consecutive_failures"] == 3
    assert row["last_ok_at"] == ok_at                  # a failure keeps the last good read
    assert row["last_item_at"] == t1                   # greatest(): never moves backwards


# ───────────────────────────── documents ─────────────────────────────


def test_documents_attachments_text_and_matches(store, tag):
    src = _source(store, tag)
    assert store.known_external_ids(src.id) == set()

    first = store.insert_document(_doc(src.id, "a1", title_orig="Nul\x00 title",
                                       structured={"note": "with\x00nul", "n": 1}))
    assert first
    again = store.insert_document(_doc(src.id, "a1", title_orig="changed"))
    assert again is None                               # ON CONFLICT (source_id, external_id)
    assert store.known_external_ids(src.id) == {"a1"}
    doc = store.db.fetchone("select title_orig, structured from document where id = %(i)s",
                            {"i": first})
    assert doc["title_orig"] == "Nul title"            # NUL dropped, never a failed insert
    assert doc["structured"] == {"note": "withnul", "n": 1}

    att = {"document_id": first, "url": "https://example.test/a1.pdf", "filename": "a1.pdf",
           "sha256": "old", "r2_key": None, "mime": "application/pdf", "bytes": 100,
           "extraction": "text", "words": 10}
    att_id = store.insert_attachment(att)
    att_again = store.insert_attachment({**att, "sha256": "new"})
    assert att_again == att_id                         # ON CONFLICT (document_id, url) → same row
    rows = store.db.fetchall("select sha256 from attachment where document_id = %(d)s",
                             {"d": first})
    assert [r["sha256"] for r in rows] == ["new"]

    store.insert_document_text(first, None, "body\x00text")
    store.insert_document_text(first, att_id, "pdf text")
    texts = store.db.fetchall(
        "select attachment_id, text from document_text where document_id = %(d)s"
        " order by attachment_id nulls first", {"d": first})
    assert [t["text"] for t in texts] == ["bodytext", "pdf text"]

    ing = _ingredient(store, tag)
    store.insert_match({"document_id": first, "attachment_id": att_id, "ingredient_id": ing,
                        "class_id": None, "term_id": None, "class_term_id": None,
                        "field": "attachment", "start_offset": 3, "end_offset": 9,
                        "matched_text": "testam", "snippet": "…testam…", "confidence": "possible"})
    m = store.db.fetchone("select * from match where document_id = %(d)s", {"d": first})
    assert str(m["ingredient_id"]) == ing and m["field"] == "attachment"
    assert m["confidence"] == "possible" and (m["start_offset"], m["end_offset"]) == (3, 9)


# ───────────────────────────── issues ─────────────────────────────


def test_issues_links_and_ingredients(store, tag):
    src = _source(store, tag)
    d1 = store.insert_document(_doc(src.id, "i1"))
    d2 = store.insert_document(_doc(src.id, "i2"))
    ing = _ingredient(store, tag)
    issue = store.create_issue(doc_type="dhpc", title="Issue", anchor_document_id=d1,
                               first_date=None, class_only=False, is_backfill=False)
    store.link_document(issue, d1, link="anchor", method="auto", score=None)
    store.link_document(issue, d1, link="copy", method="manual", score=5)   # conflict: kept
    store.link_document(issue, d2, link="copy", method="auto", score=80)
    links = store.db.fetchall(
        "select document_id, link::text as link, method::text as method, score"
        " from issue_document where issue_id = %(i)s order by score nulls first", {"i": issue})
    assert [(str(r["document_id"]), r["link"], r["method"], r["score"]) for r in links] == [
        (d1, "anchor", "auto", None), (d2, "copy", "auto", 80)]

    store.add_issue_ingredients(issue, [ing, ing])
    store.add_issue_ingredients(issue, [ing])
    rows = store.db.fetchall("select ingredient_id from issue_ingredient where issue_id = %(i)s",
                             {"i": issue})
    assert [str(r["ingredient_id"]) for r in rows] == [ing]

    alert = store.issue_for_alert(issue)
    assert alert["ingredient_ids"] == [ing]
    assert alert["country_name"] == "Finland" and str(alert["document_id"]) == d1


def test_class_only_issues_since_newest_first(store, tag):
    src = _source(store, tag)
    doc = store.insert_document(_doc(src.id, "c1"))
    since = store.db.fetchone("select now() as t")["t"]

    def make(class_only: bool, backfill: bool) -> str:
        return store.create_issue(doc_type="safety_update", title=f"class {tag}",
                                  anchor_document_id=doc, first_date=None,
                                  class_only=class_only, is_backfill=backfill)

    older = make(True, False)
    make(False, False)                                 # not class-only
    make(True, True)                                   # backfill: never in a digest
    newer = make(True, False)
    got = [i for i in store.class_only_issues_since(since) if i in (older, newer)]
    assert got == [newer, older]
    assert newer not in store.class_only_issues_since(datetime.now(timezone.utc)
                                                      + timedelta(hours=1))


def test_a_class_paper_is_never_in_the_digest_nor_an_alert(store, tag):
    # NCBI papers are read on the Ingredients screen and in the weekly report, never on Telegram.
    src = _source(store, tag)
    lit = SourceConfig(id=f"t-{tag}-lit", regulator_id=src.regulator_id, kind="literature", channel="api",
                       url=f"https://example.test/{tag}/esearch", parser="pubmed", languages=["en"],
                       schedule="daily", enabled=True, options={}, expected_max_gap_days=30)
    store.upsert_catalogue_source(lit, "papers")
    since = store.db.fetchone("select now() as t")["t"]
    notice = store.create_issue(doc_type="dhpc", title=f"class notice {tag}",
                                anchor_document_id=store.insert_document(_doc(src.id, "c1")),
                                first_date=None, class_only=True, is_backfill=False)
    paper = store.create_issue(doc_type="literature", title=f"class paper {tag}",
                               anchor_document_id=store.insert_document(
                                   _doc(lit.id, "p1", doc_type="literature", lang="en")),
                               first_date=None, class_only=True, is_backfill=False)
    got = store.class_only_issues_since(since)
    assert notice in got and paper not in got
    assert store.issue_for_alert(paper)["source_kind"] == "literature"
    assert store.issue_for_alert(notice)["source_kind"] == "safety"


def test_possible_case_reports_for_the_daily_message(store, tag):
    # A paper naming the ingredient that PubMed types Case Reports, or whose title says so, is listed for the
    # daily message; a class-only paper, history, a paper that is no case report, and one found earlier are not.
    src = _source(store, tag)
    lit = SourceConfig(id=f"t-{tag}-lit", regulator_id=src.regulator_id, kind="literature", channel="api",
                       url=f"https://example.test/{tag}/esearch", parser="pubmed", languages=["en"],
                       schedule="daily", enabled=True, options={}, expected_max_gap_days=30)
    store.upsert_catalogue_source(lit, "papers")
    ing = _ingredient(store, tag)
    since = store.db.fetchone("select now() as t")["t"]

    def paper(ext: str, title: str, structured: dict, *, class_only: bool = False, backfill: bool = False) -> str:
        doc = store.insert_document(_doc(lit.id, ext, doc_type="literature", lang="en", title_orig=title,
                                         structured=structured))
        issue = store.create_issue(doc_type="literature", title=title, anchor_document_id=doc, first_date=None,
                                   class_only=class_only, is_backfill=backfill)
        store.add_issue_ingredients(issue, [ing])
        return issue

    typed = paper("c1", f"Hepatitis after testamine {tag}",
                  {"pmid": "1", "journal": "Drug Saf", "pubtype": ["Journal Article", "Case Reports"],
                   "case_report": {"reason": "pubtype"}})
    titled = paper("c2", f"Testamine {tag}: a case series", {"pmid": "2", "pubtype": ["Journal Article"]})
    paper("c3", f"A cohort study of testamine {tag}", {"pmid": "3", "pubtype": ["Journal Article"]})
    paper("c4", f"Class paper {tag}: a case report", {"pmid": "4"}, class_only=True)
    paper("c5", f"History {tag}: a case report", {"pmid": "5"}, backfill=True)
    got = {r["id"]: r for r in store.case_report_papers_since(since)}
    assert set(got) == {typed, titled}
    assert got[typed]["journal"] == "Drug Saf" and got[typed]["ingredients"] == [f"testamine-{tag}"]
    assert got[typed]["ingredient_ids"] == [ing] and got[typed]["title_orig"].startswith("Hepatitis")
    assert got[typed]["day_zero"] == store.db.fetchone(
        "select (now() at time zone 'Africa/Cairo')::date as d")["d"]
    assert store.case_report_papers_since(datetime.now(timezone.utc) + timedelta(hours=1)) == []


# ───────────────────────────── alerts ─────────────────────────────


def test_notifications(store, tag):
    src = _source(store, tag)
    doc = store.insert_document(_doc(src.id, "n1"))
    issue = store.create_issue(doc_type="dhpc", title="n", anchor_document_id=doc,
                               first_date=None, class_only=False, is_backfill=False)
    p = _person(store, tag, "Notified")

    assert not store.notified(p, issue, "immediate")
    store.insert_notification(person_id=p, issue_id=issue, kind="immediate", dry_run=True,
                              tg_message_id=None, error="chat not found", summary=f"fail {tag}")
    assert not store.notified(p, issue, "immediate")   # a failed send is not a notification
    store.insert_notification(person_id=p, issue_id=issue, kind="immediate", dry_run=False,
                              tg_message_id=987654321012, error=None, summary=f"ok {tag}")
    assert store.notified(p, issue, "immediate")
    assert not store.notified(p, issue, "digest")
    store.insert_notification(person_id=p, issue_id=issue, kind="digest", dry_run=True,
                              tg_message_id=None, error=None, summary=f"digest dry {tag}")
    assert store.notified(p, issue, "digest")                       # a dry run's own once-only rule
    assert not store.notified(p, issue, "digest", real_only=True)   # the real digest still carries it

    store.insert_notification(person_id=None, issue_id=None, kind="report", dry_run=True,
                              tg_message_id=None, error=None, summary=f"report ok {tag}")
    store.insert_notification(person_id=None, issue_id=None, kind="report", dry_run=True,
                              tg_message_id=None, error="boom", summary=f"report fail {tag}")
    at = {r["summary"]: r["sent_at"] for r in store.db.fetchall(
        "select summary, sent_at from notification where summary like %(s)s",
        {"s": f"report % {tag}"})}
    assert store.last_notification_at("report") == at[f"report fail {tag}"]
    assert store.last_notification_at("report", delivered_only=True, dry_run=True) == at[f"report ok {tag}"]
    # what really went out: a dry-run row counts only for a dry run
    store.insert_notification(person_id=None, issue_id=None, kind="report", dry_run=False,
                              tg_message_id=31, error=None, summary=f"report real {tag}")
    store.insert_notification(person_id=None, issue_id=None, kind="report", dry_run=True,
                              tg_message_id=None, error=None, summary=f"report dry {tag}")
    at = {r["summary"]: r["sent_at"] for r in store.db.fetchall(
        "select summary, sent_at from notification where summary like %(s)s",
        {"s": f"report % {tag}"})}
    assert store.last_notification_at("report", delivered_only=True) == at[f"report real {tag}"]
    assert store.last_notification_at("report", delivered_only=True, dry_run=True) == at[f"report dry {tag}"]


def test_notified_since_counts_what_reached_the_person(store, tag):
    p = _person(store, tag, "Daily")
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert not store.notified_since(p, "new_items_digest", since)
    store.insert_notification(person_id=p, issue_id=None, kind="new_items_digest", dry_run=False,
                              tg_message_id=None, error="Forbidden", summary=f"refused {tag}")
    assert not store.notified_since(p, "new_items_digest", since)    # refused: tried again
    store.insert_notification(person_id=p, issue_id=None, kind="new_items_digest", dry_run=True,
                              tg_message_id=None, error=None, summary=f"dry {tag}")
    assert not store.notified_since(p, "new_items_digest", since)    # a dry run never takes the real one
    assert store.notified_since(p, "new_items_digest", since, dry_run=True)  # a dry run is once a day
    # a real delivered row counts (a kind no other test counts across people, as the database is shared)
    store.insert_notification(person_id=p, issue_id=None, kind="health", dry_run=False,
                              tg_message_id=4243, error=None, summary=f"sent {tag}")
    assert store.notified_since(p, "health", since)
    assert not store.notified_since(p, "digest", since)
    assert not store.notified_since(p, "new_items_digest", datetime.now(timezone.utc) + timedelta(hours=1))


def test_told_since_names_the_people_a_message_really_reached(store, tag):
    """The morning reminder's gate (collectors/reminders.py): a person counts as told when a delivered row of
    the kind exists since ``since``; a refused row never counts; a dry-run row counts only for a dry run."""
    p1 = _person(store, tag, "Told One")
    p2 = _person(store, tag, "Told Two")
    p3 = _person(store, tag, "Told Three")
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    assert store.told_since("escalation", since) == set()
    store.insert_notification(person_id=p1, issue_id=None, kind="escalation", dry_run=False,
                              tg_message_id=4242, error=None, summary=f"reminder ok {tag}")
    store.insert_notification(person_id=p2, issue_id=None, kind="escalation", dry_run=False,
                              tg_message_id=None, error="Forbidden", summary=f"reminder refused {tag}")
    store.insert_notification(person_id=p3, issue_id=None, kind="escalation", dry_run=True,
                              tg_message_id=None, error=None, summary=f"reminder dry {tag}")
    assert store.told_since("escalation", since) == {p1}
    assert store.told_since("escalation", since, dry_run=True) == {p1, p3}
    assert store.told_since("new_items_digest", since) == set()
    assert store.told_since("escalation", datetime.now(timezone.utc) + timedelta(hours=1)) == set()
    # a part refused after a delivered one: the reminder has not fully reached p1 until that part goes
    store.insert_notification(person_id=p1, issue_id=None, kind="escalation", dry_run=False,
                              tg_message_id=None, error="Too Many Requests", summary=f"reminder part 2 {tag}")
    assert store.told_since("escalation", since) == set()
    assert f"reminder ok {tag}" in store.delivered_texts(p1, "escalation", since)
    assert f"reminder part 2 {tag}" not in store.delivered_texts(p1, "escalation", since)
    store.insert_notification(person_id=p1, issue_id=None, kind="escalation", dry_run=False,
                              tg_message_id=4244, error=None, summary=f"reminder part 2 {tag}")
    assert store.told_since("escalation", since) == {p1}


def test_new_item_counts_are_new_items_per_country(store, tag):
    country = f"Testland {tag}"
    store.upsert_regulator({"id": f"NI-{tag}", "country_code": "XN", "country_name": country,
                            "name": f"New items regulator {tag}", "languages": ["en"], "homepage": None})
    for kind in ("safety", "spc"):
        store.upsert_catalogue_source(SourceConfig(
            id=f"ni-{kind}-{tag}", regulator_id=f"NI-{tag}", kind=kind, channel="html",
            url=f"https://example.test/ni/{kind}/{tag}", parser="generic_html", languages=["en"],
            schedule="4h", enabled=True, options={}, expected_max_gap_days=None), None)
    t0 = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
    for sid, ext, at, backfill in ((f"ni-safety-{tag}", "a", t0, False),
                                   (f"ni-safety-{tag}", "b", t0 + timedelta(hours=1), False),
                                   (f"ni-safety-{tag}", "h", t0, True),          # history
                                   (f"ni-spc-{tag}", "s", t0, False),             # the label watch
                                   (f"ni-safety-{tag}", "late", t0 + timedelta(days=2), False)):
        did = store.insert_document(_doc(sid, f"{ext}-{tag}", is_backfill=backfill))
        store.db.execute("update document set first_seen_at = %(t)s where id = %(i)s", {"t": at, "i": did})
    counts = [c for c in store.new_item_counts(t0, t0 + timedelta(days=1)) if c["country_name"] == country]
    assert counts == [{"country_name": country, "n": 2}]


def test_subscribers(store, tag):
    ing = _ingredient(store, tag)
    other = _ingredient(store, tag + "x")
    watcher = _person(store, tag, "Watcher")
    admin = _person(store, tag, "Admin", role="admin")
    gone = _person(store, tag, "Gone", active=False)
    unlinked = _person(store, tag, "Unlinked", chat=False)
    not_admin = _person(store, tag, "Reader")
    for person, kind, ingredient in ((watcher, "ingredient", ing), (admin, "ingredient", None),
                                     (gone, "ingredient", ing), (unlinked, "ingredient", ing),
                                     (admin, "admin_health", None),
                                     (not_admin, "admin_health", None)):
        store.db.execute(
            "insert into subscription (person_id, kind, ingredient_id) values (%(p)s, %(k)s, %(i)s)",
            {"p": person, "k": kind, "i": ingredient})
    mine = {watcher, admin, gone, unlinked, not_admin}

    def ids(rows):
        return {r["person_id"] for r in rows} & mine

    for_ing = store.subscribers("ingredient", [ing])
    assert ids(for_ing) == {watcher, admin}            # inactive and unlinked people are skipped
    row = next(r for r in for_ing if r["person_id"] == watcher)
    assert row["role"] == "reviewer" and row["full_name"] == f"Watcher {tag}"
    assert ids(store.subscribers("ingredient", [other])) == {admin}   # null = every ingredient
    assert ids(store.subscribers("admin_health")) == {admin}          # admins only


def test_admins_need_no_subscription(store, tag):
    """The monthly report goes to every active, linked admin, with or without "Source health alerts"."""
    qppv = _person(store, tag, "QPPV", role="admin")
    gone = _person(store, tag, "GoneAdmin", role="admin", active=False)
    unlinked = _person(store, tag, "UnlinkedAdmin", role="admin", chat=False)
    reviewer = _person(store, tag, "Reviewer")
    mine = {qppv, gone, unlinked, reviewer}
    assert {r["person_id"] for r in store.admins()} & mine == {qppv}


def test_refused_notifications_wait_for_a_retry(store, tag):
    src = _source(store, tag)
    doc = store.insert_document(_doc(src.id, "r1"))
    issue = store.create_issue(doc_type="dhpc", title="r", anchor_document_id=doc,
                               first_date=None, class_only=False, is_backfill=False)
    p = _person(store, tag, "Refused")
    since = store.db.fetchone("select now() - interval '1 minute' as t")["t"]
    store.insert_notification(person_id=p, issue_id=issue, kind="immediate", dry_run=False,
                              tg_message_id=None, error="Bad Gateway", summary=f"r {tag}")
    store.insert_notification(person_id=p, issue_id=issue, kind="digest", dry_run=False,
                              tg_message_id=None, error="Forbidden", summary=f"d {tag}")
    assert store.refused_alerts(since).get(issue) == {p}
    assert p in store.refused_people("digest", since)
    future = store.db.fetchone("select now() + interval '1 hour' as t")["t"]
    assert issue not in store.refused_alerts(future)
    store.insert_notification(person_id=p, issue_id=issue, kind="immediate", dry_run=False,
                              tg_message_id=123456789012, error=None, summary=f"r ok {tag}")
    store.insert_notification(person_id=p, issue_id=issue, kind="digest", dry_run=False,
                              tg_message_id=123456789013, error=None, summary=f"d ok {tag}")
    assert issue not in store.refused_alerts(since)
    assert p not in store.refused_people("digest", since)
    assert store.last_notification_at("digest", delivered_only=True, before=since) != \
        store.last_notification_at("digest", delivered_only=True)


def test_a_digest_delivered_partway_still_owes_the_rest(store, tag):
    src = _source(store, tag)
    doc = store.insert_document(_doc(src.id, "pw"))
    a = store.create_issue(doc_type="dhpc", title="a", anchor_document_id=doc,
                           first_date=None, class_only=True, is_backfill=False)
    b = store.create_issue(doc_type="dhpc", title="b", anchor_document_id=doc,
                           first_date=None, class_only=True, is_backfill=False)
    p = _person(store, tag, "Partway")
    since = store.db.fetchone("select now() - interval '1 minute' as t")["t"]
    store.insert_notification(person_id=p, issue_id=a, kind="digest", dry_run=False,
                              tg_message_id=123456789014, error=None, summary=f"part 1 {tag}")
    store.insert_notification(person_id=p, issue_id=b, kind="digest", dry_run=False,
                              tg_message_id=None, error="Too Many Requests", summary=f"part 2 {tag}")
    assert p in store.refused_people("digest", since)
    store.insert_notification(person_id=p, issue_id=b, kind="digest", dry_run=False,
                              tg_message_id=123456789015, error=None, summary=f"part 2 ok {tag}")
    assert p not in store.refused_people("digest", since)


def test_a_fresh_anchor_clears_the_backfill_flag(store, tag):
    src = _source(store, tag)
    d1 = store.insert_document(_doc(src.id, "b1", is_backfill=True))
    d2 = store.insert_document(_doc(src.id, "b2"))
    issue = store.create_issue(doc_type="dhpc", title="b", anchor_document_id=d1,
                               first_date=None, class_only=False, is_backfill=True)
    store.set_issue_anchor(issue, d2, title="anchor", doc_type="dhpc", first_date=None)
    assert store.issue_for_alert(issue)["is_backfill"] is True       # the default keeps it
    store.set_issue_anchor(issue, d2, title="anchor", doc_type="dhpc", first_date=None, is_backfill=False)
    assert store.issue_for_alert(issue)["is_backfill"] is False


def test_a_fresh_copy_marks_a_history_issue_current(store, tag):
    src = _source(store, tag)
    d1 = store.insert_document(_doc(src.id, "h1", is_backfill=True))
    issue = store.create_issue(doc_type="dhpc", title="h", anchor_document_id=d1,
                               first_date=None, class_only=False, is_backfill=True)
    store.mark_issue_current(issue)
    assert store.issue_for_alert(issue)["is_backfill"] is False


def test_a_class_issue_revived_from_history_is_in_the_digest(store, tag):
    src = _source(store, tag)
    d1 = store.insert_document(_doc(src.id, "cr", is_backfill=True))
    issue = store.create_issue(doc_type="dhpc", title="c", anchor_document_id=d1,
                               first_date=None, class_only=True, is_backfill=True)
    since = store.db.fetchone("select now() + interval '1 second' as t")["t"]
    store.db.execute("update issue set created_at = now() - interval '30 days' where id = %(i)s", {"i": issue})
    assert issue not in store.class_only_issues_since(since)
    store.db.execute("update issue set is_backfill = false, current_since = now() + interval '1 minute' "
                     "where id = %(i)s", {"i": issue})
    assert issue in store.class_only_issues_since(since)
    store.db.execute("update issue set is_backfill = true, current_since = null where id = %(i)s", {"i": issue})
    store.mark_issue_current(issue)
    row = store.db.fetchone("select current_since from issue where id = %(i)s", {"i": issue})
    assert row["current_since"] is not None


@pytest.mark.parametrize("error, failed", [
    (None, False), ("imap not configured", False),
    ("imap: 2 message(s) held unread: sender not verified (no DMARC, DKIM or SPF pass) or too big", False),
    ("imap: ConnectionRefusedError: refused", False),
    ("3 item(s) failed; first: x: ValueError: y", False),
    ("time budget reached: 40 new item(s) wait for the next run", False),
    ("imap not configured; time budget reached: 4 new item(s) wait for the next run", False),
    ("item cap reached: 212 new item(s) wait for the next run", False),
    ("2 error(s); first: HTTP 503", False), ("1 product(s) without label text", False),
    ("blocked: bot check at https://x", True), ("parse: the page changed shape", True),
    ("FetchError: every new item failed; first: x", True), ("ConnectError: timed out", True),
    ("no label read: no product found", True),
])
def test_one_definition_of_a_failed_run(store, error, failed):
    got = store.db.fetchone("select source_run_failed(%(e)s) as f", {"e": error})["f"]
    assert got is failed


# ───────────────────────────── NCBI literature (migration 0035) ─────────────────────────────


def test_literature_searches_remember_their_look_back(store, tag):
    q = f"testamine-{tag}"
    assert ("pmc", q) not in store.literature_searches()
    row = {"db": "pmc", "query": q, "kind": "name", "look_back_from": date(2025, 11, 6),
           "history_until": date(2026, 11, 6), "done": False}
    store.save_literature_searches([row, {**row, "db": "pubmed", "done": True}])
    got = store.literature_searches()
    assert got[("pmc", q)]["look_back_done_at"] is None
    assert got[("pmc", q)]["look_back_from"] == date(2025, 11, 6)
    assert got[("pmc", q)]["history_until"] == date(2026, 11, 6)
    assert got[("pmc", q)]["last_searched_at"] is not None
    first_done = got[("pubmed", q)]["look_back_done_at"]
    assert first_done is not None and got[("pubmed", q)]["kind"] == "name"

    store.save_literature_searches([{**row, "done": True}, {**row, "db": "pubmed", "done": True}])
    got = store.literature_searches()
    assert got[("pmc", q)]["look_back_done_at"] is not None
    assert got[("pubmed", q)]["look_back_done_at"] == first_done      # finished once: kept

    # searched again after months away: a new look-back, not finished yet
    store.save_literature_searches([{**row, "db": "pubmed", "look_back_from": date(2026, 6, 1)}])
    again = store.literature_searches()[("pubmed", q)]
    assert again["look_back_done_at"] is None and again["look_back_from"] == date(2026, 6, 1)
    store.save_literature_searches([])                                  # nothing to save: no error


def test_class_words_and_known_paper_ids(store, tag):
    ing = _ingredient(store, tag)
    cls = str(store.db.fetchone(
        "insert into drug_class (code, name_en) values (%(c)s, %(n)s) returning id",
        {"c": f"T{tag}", "n": f"Testaminoids {tag}"})["id"])
    store.db.execute("insert into ingredient_class (ingredient_id, class_id) values (%(i)s, %(c)s)",
                     {"i": ing, "c": cls})
    store.db.execute(
        """insert into class_term (class_id, lang, term) values
             (%(c)s, 'en', %(b)s), (%(c)s, 'en', %(a)s), (%(c)s, 'de', %(d)s)""",
        {"c": cls, "a": f"atestaminoids {tag}", "b": f"btestaminoids {tag}", "d": f"Testaminoide {tag}"})
    assert store.class_words("en")[f"testamine-{tag}"] == [f"atestaminoids {tag}", f"btestaminoids {tag}"]
    assert store.class_words("de")[f"testamine-{tag}"] == [f"Testaminoide {tag}"]
    store.db.execute("update ingredient set active = false where id = %(i)s", {"i": ing})
    assert f"testamine-{tag}" not in store.class_words("en")

    src = _source(store, tag)
    store.insert_document(_doc(src.id, "42979212", structured={"pmid": "42979212", "pmcid": "PMC13730105"}))
    store.insert_document(_doc(src.id, "PMC13727276", structured={"pmid": None, "pmcid": "PMC13727276"}))
    store.insert_document(_doc(src.id, "42846100", structured={"pmid": "42846100"}))
    assert store.literature_known_ids(src.id) == {"42979212", "PMC13730105", "PMC13727276", "42846100"}


def test_issues_of_papers_are_never_merge_candidates(store, tag):
    src = _source(store, tag)
    ing = _ingredient(store, tag)
    when = datetime(2026, 10, 1).date()
    for n, doc_type in enumerate(("literature", "dhpc")):
        doc = store.insert_document(_doc(src.id, f"m{n}", doc_type=doc_type))
        issue = store.create_issue(doc_type=doc_type, title=f"t{n}", anchor_document_id=doc,
                                   first_date=when, class_only=False, is_backfill=False)
        store.link_document(issue, doc, link="anchor", method="auto", score=None)
        store.add_issue_ingredients(issue, [ing])
    got = store.candidate_issues([ing], when - timedelta(days=1), when + timedelta(days=1))
    assert [i["doc_type"] for i in got] == ["dhpc"]


# ───────────────────────────── packs on request (0048) ─────────────────────────────

def _pack_request(store: Store, ing: str, person: str, *, asked: str = "2000-01-01T00:00:00Z") -> str:
    """A request as request_report() writes it (the collectors' connection is the owner: a direct insert)."""
    row = store.db.fetchone(
        """insert into report_request (kind, ingredient_id, from_day, to_day, requested_by, requested_at)
           values ('psur', %(i)s, '2025-01-01', '2025-12-31', %(p)s, %(a)s) returning id::text as id""",
        {"i": ing, "p": person, "a": asked})
    return row["id"]


def _pack_row(store: Store, rid: str) -> dict:
    return store.db.fetchone("select * from report_request where id = %(id)s::uuid", {"id": rid})


def test_a_pack_request_is_claimed_once_requeued_and_finished(store, tag):
    ing = _ingredient(store, tag)
    who = _person(store, tag, "Asker")
    rid = _pack_request(store, ing, who)
    assert store.report_requests_waiting() >= 1
    got = store.claim_report_request()
    assert got["id"] == rid and got["kind"] == "psur" and got["attempts"] == 1
    assert got["from_day"] == date(2025, 1, 1) and got["to_day"] == date(2025, 12, 31)
    assert got["requested_by"] == who and got["requested_by_name"] == f"Asker {tag}"
    assert got["ingredient_name"] == f"testamine-{tag}"
    row = _pack_row(store, rid)
    assert row["status"] == "building" and row["started_at"] is not None
    # a second run in the meantime does not take it
    again = store.claim_report_request()
    assert again is None or again["id"] != rid
    if again:
        store.fail_report_request(again["id"], "not this test's")
    # cut short by its budget: it waits again, with the note
    store.requeue_report_request(rid, "Took longer than 15 minutes; the next collection run goes on with it.")
    row = _pack_row(store, rid)
    assert row["status"] == "queued" and row["error"].startswith("Took longer")
    assert store.claim_report_request()["attempts"] == 2
    # a run that died: taken again once its build is two hours old
    store.db.execute("update report_request set started_at = now() - interval '3 hours' where id = %(id)s::uuid",
                     {"id": rid})
    assert store.claim_report_request()["attempts"] == 3
    store.finish_report_request(rid, pdf_r2_key=f"reports/packs/psur/{rid}/x.pdf", pdf_sha256="4" * 64,
                                xlsx_r2_key=f"reports/packs/psur/{rid}/x.xlsx", xlsx_sha256="5" * 64,
                                git_sha="abc123", made_by_run="https://github.com/x/y/actions/runs/1")
    row = _pack_row(store, rid)
    assert row["status"] == "done" and row["error"] is None and row["made_at"] is not None
    assert row["pdf_sha256"] == "4" * 64 and row["git_sha"] == "abc123"
    fp = store.db.fetchone(
        """select encode(sha256(convert_to(pdf_sha256 || ':' || xlsx_sha256, 'UTF8')), 'hex') as fp
             from report_request where id = %(id)s::uuid""", {"id": rid})["fp"]
    assert len(fp) == 64


def test_a_pack_request_that_fails_keeps_its_reason(store, tag):
    ing = _ingredient(store, tag)
    who = _person(store, tag, "Asker")
    rid = _pack_request(store, ing, who)
    got = store.claim_report_request()
    assert got["id"] == rid
    store.fail_report_request(rid, "RuntimeError: canceling statement due to statement timeout")
    row = _pack_row(store, rid)
    assert row["status"] == "failed" and "statement timeout" in row["error"]
    # a failed request never waits again: asking again makes a new one
    assert rid not in {r["id"] for r in store.db.fetchall(
        "select id::text as id from report_request where status in ('queued', 'building')")}


class _RollBack(Exception):
    """Raised to undo a test's rows that cannot be deleted (a signature, an audit row)."""


def test_a_signed_signal_matches_in_the_inspection_pack(store, tag):
    """The inspection pack's signatures read each record's fingerprint now on the collector's connection (no
    session, so record_fingerprint() is null there): its SQL must compute a signal's exactly as 0048 does."""
    from collectors import report_pack as rp

    db = store.db
    try:
        with db.transaction():
            who = _person(store, tag, "Signer", role="admin")
            sig = db.fetchone(
                """insert into signal (ref, title, opened_by, validation_due)
                   values (%(r)s, %(t)s, %(p)s::uuid, current_date + 30) returning id::text as id""",
                {"r": f"SIG-T-{tag}", "t": f"Test signal {tag}", "p": who})["id"]
            db.execute("""insert into signal_event (signal_id, step, to_stage, person_id)
                          values (%(s)s::uuid, 'opened', 'validation', %(p)s::uuid)""", {"s": sig, "p": who})
            # the fingerprint a signer signs: record_fingerprint() in the CI Admin's session
            db.execute("""select set_config('request.jwt.claims',
                            '{"sub":"00000000-0000-0000-0000-0000000000a1","role":"authenticated"}', true)""")
            fp = db.fetchone("select record_fingerprint('signal', %(s)s::uuid) as fp", {"s": sig})["fp"]
            db.execute("select set_config('request.jwt.claims', '', true)")
            assert fp and len(fp) == 64
            db.execute(
                """insert into sign_off (record_kind, record_id, record_sha256, meaning, person_id, signed_name,
                                         signed_role)
                   values ('signal', %(s)s::uuid, %(fp)s, 'approved', %(p)s::uuid, 'Signer', 'admin')""",
                {"s": sig, "fp": fp, "p": who})
            now = datetime.now(timezone.utc)
            rows = db.fetchall(rp.SIGNATURES_SQL, {"a": now - timedelta(hours=1), "b": now + timedelta(hours=1)})
            mine = [r for r in rows if r["record_id"] == sig]
            assert len(mine) == 1
            assert mine[0]["signal_ref"] == f"SIG-T-{tag}"
            assert mine[0]["fingerprint_now"] == fp, "a signal signed and unchanged must match its signature"
            raise _RollBack
    except _RollBack:
        pass


def test_the_matching_audit_finds_candidates_in_the_database_and_keeps_its_row(store, tag):
    src = _source(store, tag)
    ing = _ingredient(store, tag)
    word = f"zq{tag}mab"
    named = store.insert_document(_doc(src.id, "m1", title_orig=f"{word.title()}: new warning"))
    in_text = store.insert_document(_doc(src.id, "m2", title_orig="Monthly letter"))
    store.insert_document_text(in_text, None, f"... the risk with {word} 100_% max ...")
    store.insert_document(_doc(src.id, "m3", title_orig="Nothing about it"))
    assert store.audit_candidates([word, "100_%x"]) == sorted([str(named), str(in_text)])
    assert store.audit_candidates(["100_%x"]) == []          # LIKE wildcards are only letters here
    docs = store.audit_documents([str(named)])
    assert docs[0]["title_orig"].startswith(word.title()) and docs[0]["issue"] is None
    store.record_match_audit([{"ingredient_id": ing, "names_checked": 1, "notices_named": 2, "unlinked_found": 1,
                               "linked_now": 1, "left_over": [], "unchecked_names": 0,
                               "flagged_names": [{"term_id": "x", "term": "Ofloxacin", "why": "RxNorm: ofloxacin"}]}])
    row = store.db.fetchone("select * from match_audit where ingredient_id = %(i)s", {"i": ing})
    assert row["linked_now"] == 1 and row["flagged_names"][0]["term"] == "Ofloxacin"
