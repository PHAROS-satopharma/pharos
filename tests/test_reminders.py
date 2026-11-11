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


class RecordingTelegram:
    """A Telegram that takes every message, or refuses the chats in ``refuse`` (a person who blocked the bot)."""

    def __init__(self, refuse: set[int] | None = None) -> None:
        self.messages: list[tuple[int, str]] = []
        self.refuse = set(refuse or ())

    def send_message(self, chat_id: int, text: str) -> int:
        from collectors.alerts import TelegramError

        if chat_id in self.refuse:
            raise TelegramError("Forbidden: bot was blocked by the user")
        self.messages.append((chat_id, text))
        return 1000 + len(self.messages)

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

    def finding(key: str, title: str, first_seen: date, *, decisions: list[str], sent: bool = False,
                created: date | None = None) -> str:
        """A notice PHAROS first showed on ``first_seen`` (its creation day; the anchor document was first seen
        the same day unless ``created`` says otherwise)."""
        did = s.insert_document({"source_id": "bfarm-rhb", "external_id": key, "lang": "de", "doc_type": "dhpc",
                                 "url": f"https://www.bfarm.de/{key}.html", "title_orig": title,
                                 "published_date": first_seen, "structured": None, "is_backfill": False})
        s.document[did]["first_seen_at"] = seen(first_seen)
        iid = s.create_issue(doc_type="dhpc", title=title, anchor_document_id=did, first_date=first_seen,
                             class_only=False, is_backfill=False)
        s.issue[iid]["created_at"] = seen(created or first_seen)
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
    s.finding = finding  # type: ignore[attr-defined]  - for the tests that add one more
    return s


def notifier_for(store: MemoryStore, **kw) -> Notifier:
    return Notifier(store, store.settings(), telegram=ExplodingTelegram(), **kw)


def real_notifier(store: MemoryStore, monkeypatch, telegram: RecordingTelegram) -> Notifier:
    """A notifier that really sends (to the recording fake): the setting off, a token in the environment."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    n = Notifier(store, {**store.settings(), "telegram_dry_run": False}, telegram=telegram)
    assert not n.dry_run
    return n


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


def test_day_zero_stays_when_the_anchor_moves_to_a_later_document():
    """collectors/merge.py moves a notice's anchor to an EMA document that arrives later; the day PHAROS first
    showed the notice does not move, so the due day does not move either (0050)."""
    s = store_with_findings()
    iid = next(i for i, r in s.issue.items() if r["title"] == "Rote-Hand-Brief <Levofloxacin>")   # shown 2 Nov
    ema = s.insert_document({"source_id": "bfarm-rhb", "external_id": "ema-a", "lang": "en", "doc_type": "dhpc",
                             "url": "https://www.ema.europa.eu/a", "title_orig": "DHPC: Levofloxacin",
                             "published_date": date(2026, 11, 5), "structured": None, "is_backfill": False})
    s.document[ema]["first_seen_at"] = seen(date(2026, 11, 5))
    s.link_document(iid, ema, link="anchor", method="auto", score=90)
    s.set_issue_anchor(iid, ema, title="DHPC: Levofloxacin", doc_type="dhpc", first_date=date(2026, 11, 5),
                       is_backfill=False)
    row = next(r for r in s.eda_reminders(TODAY, within_days=2) if r["issue_id"] == iid)
    assert row["title"] == "DHPC: Levofloxacin"
    assert (row["day_zero"], row["due"], row["days_left"]) == (date(2026, 11, 2), date(2026, 11, 7), 1)


def test_a_notice_created_today_for_an_old_document_is_due_in_five_days_not_late():
    """A re-match creates a notice for a document first seen 175 days ago: PHAROS first showed it today."""
    s = store_with_findings()
    iid = s.finding("old", "Levofloxacin: alte Meldung", date(2026, 5, 15), decisions=["relevant"], created=TODAY)
    assert iid not in {r["issue_id"] for r in s.eda_reminders(TODAY, within_days=2)}, "due in 5 days: not yet"
    row = next(r for r in s.eda_reminders(TODAY, within_days=5) if r["issue_id"] == iid)
    assert (row["day_zero"], row["due"], row["days_left"], row["clock"]) == (TODAY, date(2026, 11, 11), 5, "running")


def test_a_report_sent_to_the_authority_is_never_forgotten():
    """Concerns us, Doesn't concern us, Concerns us again: the report sent under the first decision still
    counts, so the reminder does not ask for a second one (0050)."""
    s = store_with_findings()
    iid = s.finding("again", "Levofloxacin: doch wieder", date(2026, 10, 25),
                    decisions=["relevant", "not_relevant", "relevant"])
    s.authority_report.append({"id": "again-s", "issue_id": iid, "decision_id": "again-d0", "sent_on": TODAY,
                               "reference": "EDA/2", "note": None, "person_id": "p1", "withdrawn_at": None,
                               "created_at": cairo(TODAY, 6, 30).astimezone(timezone.utc)})
    assert iid not in {r["issue_id"] for r in s.eda_reminders(TODAY, within_days=2)}


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


@pytest.mark.parametrize("wall", [datetime(2020, 1, 1, 12, tzinfo=timezone.utc),     # long before the test days
                                  datetime(2026, 11, 6, 20, tzinfo=timezone.utc),    # the same Cairo day, late
                                  datetime(2031, 5, 5, 12, tzinfo=timezone.utc)])    # long after: what CI hit on 7 Nov
def test_the_day_follows_the_injected_clock_never_the_wall_clock(monkeypatch, wall):
    """The rows the reminder writes carry the clock it was given, so "told today" is cut from the same clock
    wherever the wall clock stands (it failed in CI from midnight Cairo on 7 Nov 2026)."""
    monkeypatch.setattr("collectors.core.memstore._now", lambda: wall)
    s = store_with_findings()
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert reminders.remind_if_due(s, notifier_for(s), now=at(20)) == 0
    assert {n["sent_at"] for n in s.notification} == {at(8)()}
    tomorrow = lambda: cairo(date(2026, 11, 7), 8).astimezone(timezone.utc)  # noqa: E731
    assert reminders.remind_if_due(s, notifier_for(s), now=tomorrow) == 2
    assert len(s.notification) == 4


def test_a_dry_run_does_not_cancel_the_day_s_real_reminder(monkeypatch):
    """A dry run after 07:00 (by hand, say) writes its rows; the real reminder of the day still goes once."""
    s = store_with_findings()
    assert reminders.remind_if_due(s, notifier_for(s, dry_run=True), now=at(7, 30)) == 2
    tg = RecordingTelegram()
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(8, 17)) == 2
    assert sorted(chat for chat, _ in tg.messages) == [111, 222]
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(12, 17)) == 0, "once a day"
    assert len(tg.messages) == 2
    assert [(r["dry_run"], r["error"]) for r in s.notification] == [(True, None), (True, None), (False, None), (False, None)]


def test_a_refused_message_is_tried_again_and_the_others_are_not_told_twice(monkeypatch):
    """Telegram refuses one chat at 08:17 (the bot blocked, a network error): the next run tells that person,
    and only that person."""
    s = store_with_findings()
    tg = RecordingTelegram(refuse={111})
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(8, 17)) == 2
    assert [chat for chat, _ in tg.messages] == [222]
    assert [(r["person_id"], r["error"] is not None) for r in s.notification] == [("p1", True), ("p2", False)]
    tg.refuse.clear()
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(12, 17)) == 1
    assert [chat for chat, _ in tg.messages] == [222, 111]
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(16, 17)) == 0
    assert len(s.notification) == 3



class PartRefusingTelegram(RecordingTelegram):
    """Refuses, for one chat, every message that starts with ``part`` (a timeout, a 429) until cleared."""

    def __init__(self, chat: int, part: str) -> None:
        super().__init__()
        self.chat, self.part = chat, part

    def send_message(self, chat_id: int, text: str) -> int:
        from collectors.alerts import TelegramError
        if self.part and chat_id == self.chat and text.startswith(self.part):
            raise TelegramError("Too Many Requests: retry after 30")
        return super().send_message(chat_id, text)


def test_a_refused_second_part_is_sent_again_without_the_first(monkeypatch):
    """Audit of 6 Nov 2026: a long reminder goes in two parts; part 2 refused at 08:17 counted the person as told,
    so the rest of the late findings never reached them that day."""
    s = store_with_findings()
    monkeypatch.setattr(reminders, "build_messages", lambda items, today, signals=(), **quality: ["PART ONE", "PART TWO"])
    tg = PartRefusingTelegram(111, "PART TWO")
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(8, 17)) == 2
    assert tg.messages == [(111, "PART ONE"), (222, "PART ONE"), (222, "PART TWO")]
    tg.part = ""
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(12, 17)) == 1
    assert tg.messages[3:] == [(111, "PART TWO")]                # only what p1 missed; p2 is not told twice
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(16, 17)) == 0
    assert len(tg.messages) == 4


def test_a_refused_first_part_holds_back_the_rest_until_it_goes(monkeypatch):
    """Part 1 carries the heading and the most-late findings: when it is refused, part 2 waits with it, and the
    next run sends both in order."""
    s = store_with_findings()
    monkeypatch.setattr(reminders, "build_messages", lambda items, today, signals=(), **quality: ["PART ONE", "PART TWO"])
    tg = PartRefusingTelegram(111, "PART ONE")
    reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(8, 17))
    assert [m for m in tg.messages if m[0] == 111] == []         # part 2 never goes alone
    assert [(r["summary"], r["error"] is not None) for r in s.notification if r["person_id"] == "p1"] == [
        ("PART ONE", True), ("PART TWO", True)]
    tg.part = ""
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(12, 17)) == 1
    assert [m for m in tg.messages if m[0] == 111] == [(111, "PART ONE"), (111, "PART TWO")]
    assert reminders.remind_if_due(s, real_notifier(s, monkeypatch, tg), now=at(16, 17)) == 0

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


# ───────────────────────────── the signal steps (0042) ─────────────────────────────

def with_signals(s: MemoryStore) -> MemoryStore:
    """Signals opened from the findings (0042): one to validate tomorrow, one assessment 3 days late, one to
    validate in 4 days (not yet), one with an action due today, one closed (never listed)."""
    titles = {r["title"]: i for i, r in s.issue.items()}

    def signal(ref: str, title: str, stage: str, *, due: date, ingredient: str | None = "ing-1",
               priority: str | None = None) -> None:
        s.signal[ref] = {"id": ref, "ref": ref, "title": title, "ingredient_id": ingredient, "stage": stage,
                         "priority": priority, "outcome": None, "validation_due": due,
                         "assessment_due": due if stage == "assessment" else None,
                         "action_due": due if stage == "action" else None,
                         "closed_at": cairo(TODAY, 6).astimezone(timezone.utc) if stage == "closed" else None}
        s.signal_issue.append({"signal_id": ref, "issue_id": titles.get(title)})

    signal("SIG-2026-003", "Rote-Hand-Brief <Levofloxacin>", "validation", due=date(2026, 11, 7))
    signal("SIG-2026-001", "Fluorchinolone: Aortenaneurysma", "assessment", due=date(2026, 11, 3), priority="high")
    signal("SIG-2026-004", "Levofloxacin: Netzhaut", "validation", due=date(2026, 11, 10))
    signal("SIG-2026-002", "Levofloxacin und Sehnen", "action", due=TODAY, priority="medium")
    signal("SIG-2026-005", "Levofloxacin: gesendet", "closed", due=date(2026, 10, 25))
    return s


def test_the_store_lists_signal_steps_late_or_due_within_two_days_most_late_first():
    s = with_signals(store_with_findings())
    rows = s.signal_reminders(TODAY, within_days=2)
    assert [(r["ref"], r["stage"], r["days_left"]) for r in rows] == [
        ("SIG-2026-001", "assessment", -3), ("SIG-2026-002", "action", 0), ("SIG-2026-003", "validation", 1)]
    assert rows[0]["next_due"] == date(2026, 11, 3) and rows[0]["title"] == "Fluorchinolone: Aortenaneurysma"
    assert all(r["ingredient"] == "levofloxacin" and r["ingredient_id"] == "ing-1" for r in rows)
    assert all("signal_id" in r for r in rows)


def test_step_text_in_her_words():
    assert reminders.step_text("validation", date(2026, 11, 7), 1) == "Validate · due Sat 7 Nov, 1 day left"
    assert reminders.step_text("assessment", date(2026, 11, 3), -3) == "Assess · 3 days late (was due Tue 3 Nov)"
    assert reminders.step_text("action", date(2026, 11, 6), 0) == "Action · due today, Fri 6 Nov"


def test_the_message_adds_the_signal_steps_after_the_findings():
    s = with_signals(store_with_findings())
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Egyptian Drug Authority · 6 Nov 2026")
    assert "<b>4 findings to report to the authority</b>" in text
    assert "<b>3 signal steps due</b>" in text
    assert "1 late, 2 due within 2 days" in text
    assert text.index("findings to report") < text.index("signal steps due"), "the findings first, then the signals"
    lines = [ln for ln in text.splitlines() if ln.startswith("• ")]
    assert lines[4:] == [
        "• SIG-2026-001 · Fluorchinolone: Aortenaneurysma · levofloxacin · Assess · 3 days late (was due Tue 3 Nov)",
        "• SIG-2026-002 · Levofloxacin und Sehnen · levofloxacin · Action · due today, Fri 6 Nov",
        "• SIG-2026-003 · Rote-Hand-Brief &lt;Levofloxacin&gt; · levofloxacin · Validate · due Sat 7 Nov, 1 day left"]
    assert text.count("https://pharos-satopharma.pages.dev/ingredients/ing-1") == 7, "a link under every line"
    for absent in ("SIG-2026-004", "SIG-2026-005"):
        assert absent not in text


def test_signal_steps_alone_are_enough_to_send():
    s = with_signals(store_with_findings())
    s.review_event.clear()                       # no finding has a running clock any more
    assert s.eda_reminders(TODAY, within_days=2) == []
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Signal steps · 6 Nov 2026")
    assert "findings to report" not in text
    assert "<b>3 signal steps due</b>" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("• ")]) == 3


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


# ───────────────────────────── the quality records (0107) ─────────────────────────────

QUALITY = "https://pharos-satopharma.pages.dev/quality"


def with_quality(s: MemoryStore) -> MemoryStore:
    """Deviations, audits and CAPAs (0107) on Fri 6 Nov 2026: one CAPA due in 2 days, one 3 days late, one done,
    one effective, one due in 14 days; one audit whose next deadline (draft CAPA, day 10) is today, one whose QPPV
    review is 16 days late, one closed, one whose next deadline is in 5 days, one only planned."""
    s.deviation["dv1"] = {"id": "dv1", "ref": "D001/2026", "year": 2026, "serial": 1,
                          "title": "Weekly report signed late", "status": "capa"}

    def audit(aid: str, title: str, kind: str, report: date | None, status: str, **done) -> None:
        s.audit[aid] = {"id": aid, "kind": kind, "title": title, "auditor": "Partner Pharma",
                        "report_received_on": report, "reviewed_on": None, "meeting_on": None,
                        "capa_drafted_on": None, "capa_approved_on": None, "capa_submitted_on": None,
                        "status": status, **done}

    audit("au1", "Partner Pharma 2026", "external", date(2026, 10, 27), "report_received",
          reviewed_on=date(2026, 10, 28), meeting_on=date(2026, 10, 29))                 # draft CAPA due today
    audit("au2", "Internal PV audit 2026", "internal", date(2026, 10, 20), "report_received")   # review 16 days late
    audit("au3", "Closed audit 2025", "external", date(2026, 10, 1), "closed",
          capa_submitted_on=date(2026, 10, 15))                                            # closed: never listed
    audit("au4", "Distributor audit", "external", date(2026, 11, 1), "report_received",
          reviewed_on=date(2026, 11, 2), meeting_on=date(2026, 11, 3))                     # draft due 11 Nov: not yet
    audit("au5", "Planned audit", "internal", None, "planned")                             # no report: no deadline
    s.audit_observation["ob2"] = {"id": "ob2", "audit_id": "au1", "number": 2}

    def capa(cid: str, serial: int, status: str, due: date | None, *, deviation: str | None = None,
             observation: str | None = None, owner: str | None = None, other: str | None = None) -> None:
        s.capa[cid] = {"id": cid, "ref": f"CAPA-{serial:03d}/2026", "year": 2026, "serial": serial,
                       "deviation_id": deviation, "observation_id": observation, "owner_id": owner,
                       "owner_other": other, "due_on": due, "status": status}

    capa("c1", 1, "approved", date(2026, 11, 8), deviation="dv1", owner="p1")                  # due in 2 days
    capa("c2", 2, "in_progress", date(2026, 11, 3), observation="ob2", other="Ahmed (Regulatory)")  # 3 days late
    capa("c3", 3, "done", date(2026, 11, 1), deviation="dv1", owner="p1")                      # done: off the list
    capa("c4", 4, "effective", date(2026, 11, 1), deviation="dv1", owner="p1")                 # effective: off
    capa("c5", 5, "approved", date(2026, 11, 20), deviation="dv1", owner="p2")                 # 14 days: not yet
    return s


def quality_only() -> MemoryStore:
    """No finding, no signal step: only the quality records are due."""
    s = with_quality(store_with_findings())
    s.review_event.clear()
    return s


def test_the_store_lists_capa_due_within_two_days_or_late_oldest_first():
    s = with_quality(store_with_findings())
    rows = s.capa_reminders(TODAY, within_days=2)
    assert [(r["ref"], r["days_left"]) for r in rows] == [("CAPA-002/2026", -3), ("CAPA-001/2026", 2)]
    assert rows[0]["source"] == "audit" and rows[0]["audit_title"] == "Partner Pharma 2026"
    assert rows[0]["observation_number"] == 2 and rows[0]["owner"] == "Ahmed (Regulatory)"
    assert rows[1]["source"] == "deviation" and rows[1]["deviation_ref"] == "D001/2026"
    assert rows[1]["owner"] == "Sama Reviewer" and rows[1]["due_on"] == date(2026, 11, 8)


def test_the_store_lists_each_open_audit_s_next_deadline_when_due_within_two_days_or_late():
    s = with_quality(store_with_findings())
    rows = s.audit_deadline_reminders(TODAY, within_days=2)
    assert [(r["title"], r["key"], r["due"], r["days_left"]) for r in rows] == [
        ("Internal PV audit 2026", "review", date(2026, 10, 21), -16),
        ("Partner Pharma 2026", "draft", date(2026, 11, 6), 0)]
    assert rows[0]["kind"] == "internal" and rows[1]["kind"] == "external"


def test_capa_and_audit_words():
    assert reminders.capa_due_text(date(2026, 11, 19), 13) == "due Thu 19 Nov"
    assert reminders.capa_due_text(date(2026, 11, 3), -3) == "late by 3 days"
    assert reminders.capa_due_text(date(2026, 11, 5), -1) == "late by 1 day"


def test_the_message_adds_capa_due_and_audit_deadlines_after_the_signals():
    s = with_quality(with_signals(store_with_findings()))
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert len(s.notification) == 2, "the same daily message, never a second one"
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Egyptian Drug Authority · 6 Nov 2026")
    assert (text.index("findings to report") < text.index("signal steps due") < text.index("<b>CAPA due</b>")
            < text.index("<b>Audit deadlines</b>")), "after the existing blocks, CAPA first"
    lines = [ln for ln in text.splitlines() if ln.startswith("• ")]
    assert lines[7:] == [
        "• CAPA-002/2026 · from Audit Partner Pharma 2026, observation 2 · Ahmed (Regulatory) · late by 3 days",
        "• CAPA-001/2026 · from D001/2026 · Sama Reviewer · due Sun 8 Nov",
        "• Internal PV audit 2026 · Internal audit · QPPV review of the report · late by 16 days",
        "• Partner Pharma 2026 · External audit · Draft CAPA · due Fri 6 Nov"]
    assert text.count(QUALITY) == 4, "a link to the Quality tab under every line"
    for absent in ("CAPA-003", "CAPA-004", "CAPA-005", "Closed audit", "Distributor audit", "Planned audit"):
        assert absent not in text


def test_the_existing_message_is_unchanged_when_no_quality_record_is_due():
    plain = store_with_findings()
    reminders.remind_if_due(plain, notifier_for(plain), now=at(8))
    s = with_quality(store_with_findings())
    for c in s.capa.values():
        c["status"] = "effective"
    for a in s.audit.values():
        a["status"] = "closed"
    reminders.remind_if_due(s, notifier_for(s), now=at(8))
    assert [n["summary"] for n in s.notification] == [n["summary"] for n in plain.notification]
    assert "CAPA" not in s.notification[0]["summary"] and "Audit deadlines" not in s.notification[0]["summary"]


def test_quality_records_alone_are_enough_to_send():
    s = quality_only()
    assert s.eda_reminders(TODAY, within_days=2) == [] and s.signal_reminders(TODAY, within_days=2) == []
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Quality · 6 Nov 2026")
    assert "findings to report" not in text and "signal steps" not in text
    assert "<b>CAPA due</b>" in text and "<b>Audit deadlines</b>" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("• ")]) == 4


def test_the_quality_blocks_go_once_a_day():
    s = quality_only()
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert reminders.remind_if_due(s, notifier_for(s), now=at(20)) == 0
    assert len(s.notification) == 2
    tomorrow = lambda: cairo(date(2026, 11, 7), 8).astimezone(timezone.utc)  # noqa: E731
    assert reminders.remind_if_due(s, notifier_for(s), now=tomorrow) == 2
    assert "late by 4 days" in s.notification[-1]["summary"]


def test_nothing_is_sent_when_no_quality_record_is_due():
    s = quality_only()
    for c in s.capa.values():
        c["status"] = "done"
    for a in s.audit.values():
        a["status"] = "closed"
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 0
    assert s.notification == []


def test_a_dry_run_writes_the_quality_text_and_never_reaches_telegram():
    s = quality_only()
    assert reminders.remind_if_due(s, notifier_for(s, dry_run=True), now=at(9)) == 2   # ExplodingTelegram
    assert all(r["dry_run"] for r in s.notification)
    assert "CAPA-002/2026" in s.notification[0]["summary"]
    assert "Draft CAPA · due Fri 6 Nov" in s.notification[1]["summary"]


def test_a_quality_read_that_fails_never_stops_the_authority_reminder(monkeypatch):
    """Before migration 0107 is applied the quality tables do not exist: the findings still go."""
    s = with_quality(store_with_findings())

    def broken(*a, **k):
        raise RuntimeError('relation "capa" does not exist')

    monkeypatch.setattr(s, "capa_reminders", broken, raising=False)
    monkeypatch.setattr(s, "audit_deadline_reminders", broken, raising=False)
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert "<b>4 findings to report to the authority</b>" in s.notification[0]["summary"]
    assert "CAPA" not in s.notification[0]["summary"]


# ───────────────────────────── proposed deviations (0108) ─────────────────────────────

def test_the_finder_runs_each_morning_even_when_nothing_else_is_due():
    s = store_with_findings()
    s.review_event.clear()
    assert reminders.remind_if_due(s, notifier_for(s), now=at(6, 59)) == 0
    assert s.proposal_runs == [], "before 07:00 nothing runs"
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 0
    assert s.proposal_runs == [TODAY] and s.notification == []


def test_proposed_deviations_waiting_are_enough_to_send_and_end_the_message():
    s = store_with_findings()
    s.review_event.clear()
    s.deviation_proposal = {"p1": {"id": "p1", "status": "proposed"}, "p2": {"id": "p2", "status": "proposed"},
                            "p3": {"id": "p3", "status": "dismissed"}}
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    text = s.notification[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · Quality · 6 Nov 2026")
    assert "<b>Proposed deviations</b>" in text
    assert "2 missed deadlines wait: record as a deviation or dismiss with the reason" in text
    assert text.rstrip().endswith(QUALITY)


def test_one_proposal_is_worded_alone_and_follows_the_quality_blocks():
    s = quality_only()
    s.deviation_proposal = {"p1": {"id": "p1", "status": "proposed"}}
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    text = s.notification[0]["summary"]
    assert "1 missed deadline waits:" in text
    assert text.index("<b>Audit deadlines</b>") < text.index("<b>Proposed deviations</b>")


def test_a_finder_that_fails_never_stops_the_authority_reminder(monkeypatch):
    """Before migration 0108 is applied the finder does not exist: the findings still go."""
    s = store_with_findings()

    def broken(*a, **k):
        raise RuntimeError("function deviation_proposals_find(date) does not exist")

    monkeypatch.setattr(s, "find_deviation_proposals", broken, raising=False)
    assert reminders.remind_if_due(s, notifier_for(s), now=at(8)) == 2
    assert "<b>4 findings to report to the authority</b>" in s.notification[0]["summary"]
    assert "Proposed deviations" not in s.notification[0]["summary"]
