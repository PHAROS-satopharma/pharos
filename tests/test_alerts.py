"""Telegram alerts. Nothing here can reach Telegram: the client is a stub, and every dry-run test uses a
stub that fails the test if it is called at all."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from collectors.alerts import Notifier, is_dry_run
from collectors.core.memstore import MemoryStore

CAIRO = ZoneInfo("Africa/Cairo")


class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called in a dry run")

    send_document = send_message


class RecordingTelegram:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.documents: list[tuple[int, dict]] = []

    def send_message(self, chat_id: int, text: str) -> int:
        self.messages.append((chat_id, text))
        return 1000 + len(self.messages)

    def send_document(self, chat_id: int, **doc) -> int:
        self.documents.append((chat_id, doc))
        return 2000 + len(self.documents)


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DRY_RUN", raising=False)


def store_with_issue(*, class_only: bool = False, is_backfill: bool = False) -> tuple[MemoryStore, str]:
    s = MemoryStore()
    s.upsert_regulator({"id": "BFARM", "country_code": "DE", "country_name": "Germany",
                        "name": "BfArM", "languages": ["de"], "homepage": None})
    s.source["bfarm-rhb"] = {"id": "bfarm-rhb", "regulator_id": "BFARM", "origin": "catalogue"}
    s.ingredient["ing-1"] = {"inn_en": "lornoxicam", "active": True}
    did = s.insert_document({"source_id": "bfarm-rhb", "external_id": "x", "lang": "de",
                             "url": "https://www.bfarm.de/x.html?a=1&b=2",
                             "title_orig": "Rote-Hand-Brief zu Xefo <8 mg> & Lornoxicam",
                             "doc_type": "dhpc", "published_date": date(2026, 10, 30),
                             "structured": None, "is_backfill": is_backfill})
    iid = s.create_issue(doc_type="dhpc", title="Rote-Hand-Brief zu Xefo", anchor_document_id=did,
                         first_date=date(2026, 10, 30), class_only=class_only, is_backfill=is_backfill)
    s.link_document(iid, did, link="anchor", method="auto", score=None)
    if not class_only:
        s.add_issue_ingredients(iid, ["ing-1"])
    for pid, name, chat, role in (("p1", "Reviewer One", 111, "reviewer"),
                                  ("p2", "Admin Two", 222, "admin"),
                                  ("p3", "No Telegram", None, "reviewer")):
        s.person[pid] = {"id": pid, "full_name": name, "telegram_chat_id": chat, "role": role,
                         "active": True}
    s.subscription += [{"person_id": "p1", "kind": "ingredient", "ingredient_id": "ing-1"},
                       {"person_id": "p2", "kind": "ingredient", "ingredient_id": None},
                       {"person_id": "p3", "kind": "ingredient", "ingredient_id": "ing-1"},
                       {"person_id": "p1", "kind": "class_digest", "ingredient_id": None},
                       {"person_id": "p2", "kind": "admin_health", "ingredient_id": None},
                       {"person_id": "p1", "kind": "admin_health", "ingredient_id": None}]
    return s, iid


def test_dry_run_is_the_default():
    assert is_dry_run({})                                   # no setting → dry run
    assert is_dry_run({"telegram_dry_run": True})


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    assert not is_dry_run({"telegram_dry_run": False})
    monkeypatch.setenv("DRY_RUN", "1")
    assert is_dry_run({"telegram_dry_run": False})
    monkeypatch.delenv("DRY_RUN")
    assert is_dry_run({"telegram_dry_run": False}, flag=True)


def test_missing_token_is_a_dry_run():
    assert is_dry_run({"telegram_dry_run": False})


def test_dry_run_writes_rows_and_never_calls_telegram():
    s, iid = store_with_issue()
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    assert n.dry_run
    assert n.issue_alert(iid) == 2                          # p3 has no chat id
    rows = s.notification
    assert {r["person_id"] for r in rows} == {"p1", "p2"}
    assert all(r["dry_run"] is True and r["kind"] == "immediate" and r["error"] is None
               and r["tg_message_id"] is None for r in rows)
    text = rows[0]["summary"]
    assert text.startswith("<b>PHAROS</b> · new notice")
    assert "<b>lornoxicam</b>" in text and "Germany · BfArM" in text
    assert "Direct healthcare professional communication · 30 Oct 2026" in text
    assert "&lt;8 mg&gt; &amp; Lornoxicam" in text          # every value escaped
    assert 'href="https://www.bfarm.de/x.html?a=1&amp;b=2"' in text
    assert n.issue_alert(iid) == 0                          # never twice to the same person


def test_dry_run_setting_true_even_with_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": True}, telegram=ExplodingTelegram())
    assert n.issue_alert(iid) == 2 and all(r["dry_run"] for r in s.notification)


def test_live_path_with_stub_client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = RecordingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    assert not n.dry_run
    assert n.issue_alert(iid) == 2
    assert sorted(c for c, _ in tg.messages) == [111, 222]
    assert all(r["dry_run"] is False and r["tg_message_id"] for r in s.notification)


def test_class_only_and_backfill_issues_are_not_immediate():
    for kw in ({"class_only": True}, {"is_backfill": True}):
        s, iid = store_with_issue(**kw)
        n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
        assert n.issue_alert(iid) == 0 and s.notification == []


def test_digest_once_a_day_after_the_hour():
    s, iid = store_with_issue(class_only=True)
    nine_ten = datetime(2026, 11, 4, 9, 10, tzinfo=CAIRO).astimezone(timezone.utc)
    s.issue[iid]["created_at"] = nine_ten - timedelta(hours=3)
    early = Notifier(s, s.settings(), telegram=ExplodingTelegram(),
                     now=lambda: nine_ten - timedelta(hours=1))
    assert early.digest_if_due() == 0                       # 08:10 Cairo: not yet
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram(), now=lambda: nine_ten)
    assert n.digest_due()
    assert n.digest_if_due() == 1                           # one class_digest subscriber
    row = s.notification[-1]
    assert row["kind"] == "digest" and row["issue_id"] == iid and row["dry_run"]
    assert "class-wide notices" in row["summary"]
    later = Notifier(s, s.settings(), telegram=ExplodingTelegram(),
                     now=lambda: nine_ten + timedelta(hours=2))
    assert not later.digest_due()                           # already sent today


def test_health_alert_goes_to_admins_only():
    s, _ = store_with_issue()
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    assert n.health_alert("bfarm-rhb", "down", "HTTP 503 <html>") == 1
    row = s.notification[-1]
    assert row["person_id"] == "p2" and row["kind"] == "health" and row["issue_id"] is None
    assert "is down" in row["summary"] and "&lt;html&gt;" in row["summary"]


def test_admin_document_dry_run():
    s, _ = store_with_issue()
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    assert n.admin_document("PHAROS-screening-2026-10.pdf", b"%PDF-1.7", "October 2026") == 1
    assert s.notification[-1]["kind"] == "report" and s.notification[-1]["dry_run"]


class RefusingTelegram(RecordingTelegram):
    """Telegram refusing the message (e.g. HTML it cannot parse) while ``refuse`` is set."""

    refuse = True

    def send_message(self, chat_id: int, text: str) -> int:
        from collectors.alerts import TelegramError

        if self.refuse:
            raise TelegramError("Bad Request: can't parse entities")
        return super().send_message(chat_id, text)


def many_class_issues(n: int) -> tuple[MemoryStore, datetime]:
    s, first = store_with_issue(class_only=True)
    nine_ten = datetime(2026, 11, 4, 9, 10, tzinfo=CAIRO).astimezone(timezone.utc)
    s.issue[first]["created_at"] = nine_ten - timedelta(hours=3)
    anchor = s.issue[first]["anchor_document_id"]
    for k in range(n - 1):
        iid = s.create_issue(doc_type="dhpc", title=f"NSAR-Hinweis {k}", anchor_document_id=anchor,
                             first_date=date(2026, 10, 30), class_only=True, is_backfill=False)
        s.link_document(iid, anchor, link="anchor", method="auto", score=None)
        s.issue[iid]["created_at"] = nine_ten - timedelta(hours=2, minutes=k)
    s.subscription.append({"person_id": "p2", "kind": "class_digest", "ingredient_id": None})
    return s, nine_ten


def test_digest_is_split_on_whole_entries(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, nine_ten = many_class_issues(40)
    tg = RecordingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg, now=lambda: nine_ten)
    assert n.digest_if_due() == 2
    to_p1 = [t for c, t in tg.messages if c == 111]
    assert len(to_p1) >= 2                                   # 40 entries do not fit one message
    for text in to_p1:
        assert len(text) <= 4000
        assert text.count("<a href=") == text.count("</a>")  # never cut inside a link
    assert sum(t.count("<a href=") for t in to_p1) == 40     # nobody's notice dropped


def test_refused_digest_is_retried_not_marked_sent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, nine_ten = many_class_issues(3)
    tg = RefusingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg, now=lambda: nine_ten)
    n.digest_if_due()
    assert tg.messages == [] and all(r["error"] for r in s.notification if r["kind"] == "digest")
    # a refused digest does not count as "sent today": the next run in the window tries again
    tg.refuse = False
    later = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg,
                     now=lambda: nine_ten + timedelta(hours=2))
    assert later.digest_due()
    assert later.digest_if_due() == 2
    assert sorted(c for c, _ in tg.messages) == [111, 222]
    # and once delivered, nobody gets it twice
    again = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg,
                     now=lambda: nine_ten + timedelta(hours=3))
    assert not again.digest_due()
