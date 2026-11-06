"""The morning reminder of the five-day clock to the Egyptian Drug Authority: once a Cairo day, from 07:00, to
every reviewer and administrator with Telegram, the findings due within 2 days or late; nothing when nothing
is due. Nothing here can reach Telegram."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from collectors import reminders
from collectors.alerts import MAX_MESSAGE_CHARS, Notifier
from collectors.core.memstore import MemoryStore

CAIRO = ZoneInfo("Africa/Cairo")
ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 6)        # a Friday; Cairo is UTC+2


class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called in a dry run")

    send_document = send_message


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)


def cairo(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m), CAIRO)


def at(h: int, m: int = 0):
    return lambda: cairo(TODAY, h, m).astimezone(timezone.utc)


def seen(day: date) -> datetime:
    """Noon in Cairo on ``day``, as the instant PHAROS first showed a notice."""
    return cairo(day, 12).astimezone(timezone.utc)


def store_with_findings() -> MemoryStore:
    s = MemoryStore()
    s.upsert_regulator({"id": "BFARM", "country_code": "DE", "country_name": "Germany", "name": "BfArM",
                        "languages": ["de"], "homepage": None})
    s.source["bfarm-rhb"] = {"id": "bfarm-rhb", "regulator_id": "BFARM", "kind": "safety"}
    s.ingredient["ing-1"] = {"id": "ing-1", "inn_en": "levofloxacin", "active": True}
    for pid, name, chat, role, active in (("p1", "Sama Reviewer", 111, "reviewer", True),
                                          ("p2", "Omar Admin", 222, "admin", True),
                                          ("p3", "Reader Three", 333, "reader", True),
                                          ("p4", "No Telegram", None, "reviewer", True),
                                          ("p5", "Gone Admin", 555, "admin", False)):
        s.person[pid] = {"id": pid, "full_name": name, "telegram_chat_id": chat, "role": role, "active": active}

    def finding(key: str, title: str, first_seen: date, *, decisions: list[str], sent: bool = False) -> str:
        did = s.insert_document({"source_id": "bfarm-rhb", "external_id": key, "lang": "de", "doc_type": "dhpc",
                                 "url": f"https://www.bfarm.de/{key}.html", "title_orig": title,
                                 "published_date": first_seen, "structured": None, "is_backfill": False})
        s.document[did]["first_seen_at"] = seen(first_seen)
        iid = s.create_issue(doc_type="dhpc", title=title, anchor_document_id=did, first_date=first_seen,
                             class_only=False, is_backfill=False)
        s.link_document(iid, did, link="anchor", method="auto", score=None)
        s.add_issue_ingredients(iid, ["ing-1"])
        for n, to in enumerate(decisions):
            s.review_event.append({"id": f"{key}-d{n}", "issue_id": iid, "to_status": to, "person_id": "p1",
                                   "created_at": cairo(TODAY, 6, n).astimezone(timezone.utc)})
        if sent:
            s.authority_report.append({"id": f"{key}-s", "issue_id": iid, "decision_id": f"{key}-d{len(decisions) - 1}",
                                       "sent_on": TODAY, "reference": "EDA/1", "note": None, "person_id": "p1",
                                       "withdrawn_at": None, "created_at": cairo(TODAY, 6, 30).astimezone(timezone.utc)})
        return iid

    finding("a", "Rote-Hand-Brief <Levofloxacin>", date(2026, 11, 2), decisions=["relevant"])      # due Sat 7 Nov
    finding("b", "Fluorchinolone: Aortenaneurysma", date(2026, 10, 29), decisions=["relevant"])    # 3 days late
    finding("c", "Levofloxacin und Sehnen", date(2026, 11, 1), decisions=["relevant"])             # due today
    finding("d", "Levofloxacin: QT", date(2026, 11, 3), decisions=["relevant"])                    # 2 days left
    finding("e", "Levofloxacin: Netzhaut", date(2026, 11, 4), decisions=["relevant"])              # 3 days left: not yet
    finding("f", "Levofloxacin: gesendet", date(2026, 10, 20), decisions=["relevant"], sent=True)  # sent: off the list
    finding("g", "Nicht unser Produkt", date(2026, 10, 20), decisions=["not_relevant"])            # clock off
    finding("h", "Doch nicht", date(2026, 10, 20), decisions=["relevant", "not_relevant"])         # reversed: off
    finding("i", "Niemand hat entschieden", date(2026, 10, 1), decisions=[])                       # no decision: off
    return s


def notifier_for(store: MemoryStore, **kw) -> Notifier:
    return Notifier(store, store.settings(), telegram=ExplodingTelegram(), **kw)


# ───────────────────────────── what is due ─────────────────────────────

def test_the_store_lists_late_and_due_within_two_days_most_late_first():
    s = store_with_findings()
    rows = s.eda_reminders(TODAY, within_days=2)
    assert [(r["title"], r["days_left"], r["clock"]) for r in rows] == [
        ("Fluorchinolone: Aortenaneurysma", -3, "late"),
        ("Levofloxacin und Sehnen", 0, "running"),
        ("Rote-Hand-Brief <Levofloxacin>", 1, "running"),
        ("Levofloxacin: QT", 2, "running")]
    assert all(r["ingredient"] == "levofloxacin" and r["ingredient_id"] == "ing-1" and r["country"] == "Germany"
               for r in rows)
    assert rows[0]["due"] == date(2026, 11, 3) and rows[0]["day_zero"] == date(2026, 10, 29)


def test_the_people_told_are_active_reviewers_and_administrators_with_telegram():
    s = store_with_findings()
    assert [p["person_id"] for p in s.reminder_people()] == ["p1", "p2"]


def test_due_text_in_her_words():
    assert reminders.due_text(date(2026, 11, 7), 1) == "due Sat 7 Nov, 1 day left"
    assert reminders.due_text(date(2026, 11, 8), 2) == "due Sun 8 Nov, 2 days left"
    assert reminders.due_text(date(2026, 11, 6), 0) == "due today, Fri 6 Nov"
    assert reminders.due_text(date(2026, 11, 5), -1) == "1 day late (was due Thu 5 Nov)"
    assert reminders.due_text(date(2026, 11, 3), -3) == "3 days late (was due Tue 3 Nov)"


# ───────────────────────────── the message ─────────────────────────────

def test_sends_once_to_every_reviewer_and_admin_as_a_dry_run():
    s = store_with_findings()
    n = reminders.remind_if_due(s, notifier_for(s), now=at(8))
    assert n == 2
    assert [(r["person_id"], r["kind"], r["dry_run"], r["issue_id"]) for r in s.notification] == [
        ("p1", "escalation", True, None), ("p2", "escalation", True, None)]
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Egyptian Drug Authority · 6 Nov 2026")
    assert "<b>4 findings to report to the authority</b>" in text
    assert "1 late, 3 due within 2 days" in text
    lines = [ln for ln in text.splitlines() if ln.startswith("• ")]
    assert lines == [
        "• Fluorchinolone: Aortenaneurysma · levofloxacin · Germany · 3 days late (was due Tue 3 Nov)",
        "• Levofloxacin und Sehnen · levofloxacin · Germany · due today, Fri 6 Nov",
        "• Rote-Hand-Brief &lt;Levofloxacin&gt; · levofloxacin · Germany · due Sat 7 Nov, 1 day left",
        "• Levofloxacin: QT · levofloxacin · Germany · due Sun 8 Nov, 2 days left"]
    assert text.count("https://pharos-satopharma.pages.dev/ingredients/ing-1") == 4, "a link under every finding"
    for absent in ("Netzhaut", "gesendet", "Nicht unser", "Doch nicht", "Niemand"):
        assert absent not in text


def test_a_dry_run_flag_writes_the_text_and_sends_nothing():
    s = store_with_findings()
    reminders.remind_if_due(s, notifier_for(s, dry_run=True), now=at(9))
    assert len(s.notification) == 2 and all(r["dry_run"] for r in s.notification)
    assert "3 days late" in s.notification[1]["summary"]


def test_once_a_cairo_day_and_again_the_next_day():
    s = store_with_findings()
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert reminders.remind_if_due(s, notifier_for(s), now=at(20)) == 0
    assert len(s.notification) == 2
    tomorrow = lambda: cairo(date(2026, 11, 7), 8).astimezone(timezone.utc)  # noqa: E731
    assert reminders.remind_if_due(s, notifier_for(s), now=tomorrow) == 2
    assert len(s.notification) == 4
    assert "2 late, 3 due within 2 days" in s.notification[-1]["summary"]  # a day later: C is late, E is in reach


def test_waits_for_seven_in_cairo():
    s = store_with_findings()
    assert reminders.remind_if_due(s, notifier_for(s), now=at(6, 59)) == 0
    # 23:30 UTC on 5 November is 01:30 on the 6th in Cairo: still too early
    assert reminders.remind_if_due(s, notifier_for(s),
                                   now=lambda: datetime(2026, 11, 5, 23, 30, tzinfo=timezone.utc)) == 0
    assert s.notification == []
    assert reminders.remind_if_due(s, notifier_for(s), now=at(7)) == 2


def test_nothing_when_nothing_is_due():
    s = store_with_findings()
    quiet = lambda: cairo(date(2026, 10, 20), 8).astimezone(timezone.utc)  # noqa: E731 - before every day zero
    assert reminders.remind_if_due(s, notifier_for(s), now=quiet) == 0
    assert s.notification == []
    empty = MemoryStore()
    empty.person["p2"] = {"id": "p2", "full_name": "Omar Admin", "telegram_chat_id": 222, "role": "admin",
                          "active": True}
    assert reminders.remind_if_due(empty, notifier_for(empty), now=at(8)) == 0
    assert empty.notification == []


def test_nobody_to_tell_writes_nothing():
    s = store_with_findings()
    for p in s.person.values():
        p["telegram_chat_id"] = None
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 0
    assert s.notification == []


def test_long_lists_split_under_the_limit():
    items = [{"issue_id": f"i{n}", "ingredient_id": "ing-1", "ingredient": "levofloxacin", "title": "x" * 150,
              "country": "Germany", "due": date(2026, 11, 7), "days_left": 1, "clock": "running"}
             for n in range(120)]
    parts = reminders.build_messages(items, TODAY)
    assert len(parts) > 1 and all(len(p) <= MAX_MESSAGE_CHARS for p in parts)
    assert "80 more" in parts[-1]
    assert parts[1].startswith("<b>PHAROS</b> (continued)")


def test_titles_are_cut_at_160():
    items = [{"issue_id": "i", "ingredient_id": "ing-1", "ingredient": "levofloxacin", "title": "y" * 400,
              "country": "Germany", "due": date(2026, 11, 7), "days_left": 1, "clock": "running"}]
    text = reminders.build_messages(items, TODAY)[0]
    assert "y" * 159 + "…" in text and "y" * 161 not in text


# ───────────────────────────── where it runs ─────────────────────────────

def test_the_collector_reminds_after_the_daily_message_and_never_on_a_backfill():
    src = (ROOT / "collectors/run.py").read_text(encoding="utf-8")
    digest = src.index("notifier.new_items_digest_if_due()")
    remind = src.index("remind_if_due(")
    assert digest < remind, "the reminder follows the daily new-items message"
    tail = src[digest:remind]
    assert "if args.backfill" not in tail, "both run in the same branch, the one a backfill never takes"
    backfill_branch = src.index("if args.backfill:\n                notifier.admin_message")
    assert backfill_branch < digest
    assert re.search(r"try:\s*\n\s*#[^\n]*\n\s*reminders\.remind_if_due\(", src), "wrapped in try"
    assert "reminder failed" in src, "a reminder failure is logged, never fails the run"
