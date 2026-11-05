"""The morning escalation: once a Cairo day, from 07:00, only when something is late, to every admin."""

from __future__ import annotations

from datetime import date, datetime, timezone

from collectors import escalate
from collectors.alerts import MAX_MESSAGE_CHARS, Notifier

LATE = [
    {"kind": "signal", "label": "SIG-2026-001", "title": "Hepatotoxicity <with> NSAIDs", "ingredient": "lornoxicam",
     "due": date(2026, 11, 1), "days_late": 4},
    {"kind": "review", "label": None, "title": "Rote-Hand-Brief Lornoxicam", "ingredient": "lornoxicam",
     "due": date(2026, 11, 4), "days_late": 1},
]


class FakeDb:
    def __init__(self, items, sent_today=False):
        self.items, self.sent_today, self.asked = items, sent_today, []

    def fetchone(self, sql, params=None):
        self.asked.append(("one", params))
        return {"x": 1} if self.sent_today else None

    def fetchall(self, sql, params=None):
        self.asked.append(("all", params))
        return self.items


class FakeStore:
    def __init__(self):
        self.rows = []

    def settings(self):
        return {"telegram_dry_run": True}

    def admins(self):
        return [{"person_id": "a1", "telegram_chat_id": 1}, {"person_id": "a2", "telegram_chat_id": 2}]

    def insert_notification(self, **kw):
        self.rows.append(kw)


def at(h, m=0):
    # 5 November 2026: Cairo is UTC+2.
    return lambda: datetime(2026, 11, 5, h - 2, m, tzinfo=timezone.utc)


def test_sends_once_to_every_admin_as_a_dry_run():
    store = FakeStore()
    n = escalate.escalate(FakeDb(LATE), store, now=at(8), notifier=Notifier(store, store.settings()))
    assert n == 2
    assert [r["kind"] for r in store.rows] == ["escalation", "escalation"]
    assert all(r["dry_run"] and r["issue_id"] is None for r in store.rows)
    text = store.rows[0]["summary"]
    assert "1 signal past due" in text and "SIG-2026-001" in text and "4 days late" in text
    assert "1 notice not reviewed in time" in text and "1 day late" in text
    assert "&lt;with&gt;" in text, "titles are escaped"


def test_waits_for_seven_cairo():
    store = FakeStore()
    db = FakeDb(LATE)
    assert escalate.escalate(db, store, now=at(6, 59), notifier=Notifier(store, store.settings())) == 0
    assert store.rows == [] and db.asked == []


def test_not_twice_a_day_and_not_when_nothing_is_late():
    store = FakeStore()
    assert escalate.escalate(FakeDb(LATE, sent_today=True), store, now=at(20),
                             notifier=Notifier(store, store.settings())) == 0
    assert escalate.escalate(FakeDb([]), store, now=at(8), notifier=Notifier(store, store.settings())) == 0
    assert store.rows == []


def test_the_day_asked_is_the_cairo_day():
    store = FakeStore()
    db = FakeDb(LATE)
    # 23:30 UTC on 4 November is 01:30 on the 5th in Cairo: too early, nothing asked.
    escalate.escalate(db, store, now=lambda: datetime(2026, 11, 4, 23, 30, tzinfo=timezone.utc),
                      notifier=Notifier(store, store.settings()))
    assert db.asked == []
    escalate.escalate(db, store, now=at(9), notifier=Notifier(store, store.settings()))
    assert db.asked[-1] == ("all", {"d": date(2026, 11, 5)})


def test_long_lists_split_under_the_limit():
    many = [{**LATE[1], "title": "x" * 150} for _ in range(120)]
    parts = escalate.build_messages(many, date(2026, 11, 5))
    assert all(len(p) <= MAX_MESSAGE_CHARS for p in parts)
    assert "80 more" in parts[-1]
