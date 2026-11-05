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


def test_monthly_report_reaches_an_admin_without_health_alerts():
    """The QPPV is an admin who never chose "Source health alerts": she gets the monthly report, never a
    health alert. A reviewer with a health subscription gets neither."""
    s, _ = store_with_issue()
    s.person["p4"] = {"id": "p4", "full_name": "QPPV Admin", "telegram_chat_id": 444, "role": "admin",
                      "active": True}
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    assert n.admin_document("PHAROS-screening-2026-10.pdf", b"%PDF-1.7", "October 2026") == 2
    assert {r["person_id"] for r in s.notification if r["kind"] == "report"} == {"p2", "p4"}
    assert n.health_alert("bfarm-rhb", "down", "HTTP 503") == 1
    assert {r["person_id"] for r in s.notification if r["kind"] == "health"} == {"p2"}


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


def test_a_class_issue_revived_from_history_reaches_the_next_digest(monkeypatch):
    # Stored as history on a seed run long before; a fresh copy made it current this morning.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, nine_ten = many_class_issues(1)
    anchor = next(iter(s.issue.values()))["anchor_document_id"]
    old = s.create_issue(doc_type="dhpc", title="NSAR-Hinweis alt", anchor_document_id=anchor,
                         first_date=date(2026, 9, 1), class_only=True, is_backfill=True)
    s.link_document(old, anchor, link="anchor", method="auto", score=None)
    s.issue[old]["created_at"] = nine_ten - timedelta(days=30)
    s.mark_issue_current(old)
    s.issue[old]["current_since"] = nine_ten - timedelta(hours=1)
    tg = RecordingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg, now=lambda: nine_ten)
    n.digest_if_due()
    assert sum(t.count("<a href=") for c, t in tg.messages if c == 111) == 2   # the new one and it


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


class PickyTelegram(RecordingTelegram):
    """Refuses one chat while ``refuse`` holds its id (a person who blocked the bot, say)."""

    refuse: int | None = 111

    def send_message(self, chat_id: int, text: str) -> int:
        from collectors.alerts import TelegramError

        if chat_id == self.refuse:
            raise TelegramError("Forbidden: bot was blocked by the user")
        return super().send_message(chat_id, text)


def _broken_entity(text: str) -> bool:
    import re

    return re.search(r"&(?!amp;|lt;|gt;)", text) is not None


def test_esc_cut_never_leaves_half_an_entity():
    from collectors.alerts import esc_cut

    for n in range(590, 610):
        out = esc_cut("x" * n + "&" * 400, 600)
        assert len(out) <= 600 and not _broken_entity(out) and out.endswith("…")
    assert esc_cut("a & b", 600) == "a &amp; b"


def test_health_alert_cuts_a_long_error_without_breaking_an_entity():
    s, _ = store_with_issue()
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    n.health_alert("bfarm-rhb", "down", "GET https://x.example/?" + "a=1&b=2&" * 200)
    assert not _broken_entity(s.notification[-1]["summary"])


def test_a_long_admin_message_is_split_under_telegrams_limit():
    s, _ = store_with_issue()
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    lines = [f"- source-{k}: {'HTTP 503 <html> & more ' * 5}"[:130] for k in range(60)]
    assert n.admin_message("Backfill finished.\n" + "\n".join(lines)) == 1
    rows = [r for r in s.notification if r["kind"] == "report"]
    assert len(rows) >= 2 and all(len(r["summary"]) <= 4000 for r in rows)
    assert rows[0]["summary"].startswith("<b>PHAROS</b>\nBackfill finished.")
    assert sum(r["summary"].count("- source-") for r in rows) == 60   # no line lost


def test_a_very_long_title_still_fits_one_alert():
    s, iid = store_with_issue()
    s.document[s.issue[iid]["anchor_document_id"]]["title_orig"] = "Lornoxicam & " * 2000
    n = Notifier(s, s.settings(), telegram=ExplodingTelegram())
    n.issue_alert(iid)
    assert all(len(r["summary"]) <= 4000 and not _broken_entity(r["summary"]) for r in s.notification)


def test_a_refused_immediate_alert_is_sent_again_on_a_later_run(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = RefusingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    n.issue_alert(iid)
    assert tg.messages == [] and all(r["error"] for r in s.notification)
    tg.refuse = False
    assert n.retry_refused_alerts() == 2
    assert sorted(c for c, _ in tg.messages) == [111, 222]
    assert n.retry_refused_alerts() == 0                     # delivered: never twice


def test_a_refused_alert_older_than_the_retry_window_is_left(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = RefusingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    n.issue_alert(iid)
    tg.refuse = False
    later = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg,
                     now=lambda: datetime.now(timezone.utc) + timedelta(days=3))
    assert later.retry_refused_alerts() == 0 and tg.messages == []


def test_a_refusal_is_retried_for_two_days_from_the_first_one_only(monkeypatch):
    # Every retry writes a new refused row; the window must not restart from it, or a person who
    # blocked the bot is retried on every run for ever.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = RefusingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    n.issue_alert(iid)
    for r in s.notification:
        r["sent_at"] -= timedelta(days=3)
    n.issue_alert(iid)                                       # yesterday's retry, refused again
    assert n.retry_refused_alerts() == 0


class TextOnlyTelegram(RecordingTelegram):
    """Delivers the text but refuses the PDF after it."""

    def send_document(self, chat_id: int, **doc) -> int:
        from collectors.alerts import TelegramError

        raise TelegramError("Bad Request: wrong file identifier/HTTP URL specified")


def test_a_refused_pdf_never_sends_the_alert_text_again(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = TextOnlyTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    monkeypatch.setattr(n, "_pdf_for", lambda issue: {"filename": "n.pdf", "url": "https://x.test/n.pdf"})
    n.issue_alert(iid)
    assert len(tg.messages) == 2 and all(r["error"] for r in s.notification)
    assert n.retry_refused_alerts() == 0 and len(tg.messages) == 2


def test_a_retry_skips_a_person_whose_two_days_are_over(monkeypatch):
    # Both refused; one of them three days ago. Retrying the issue for the other must not reach them.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, iid = store_with_issue()
    tg = RefusingTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg)
    n.issue_alert(iid)
    old = s.notification[0]["person_id"]
    for r in s.notification:
        if r["person_id"] == old:
            r["sent_at"] -= timedelta(days=3)
    tg.refuse = False
    assert n.retry_refused_alerts() == 1
    assert len(tg.messages) == 1 and not s.notified(old, iid, "immediate")


class SecondPartRefusedTelegram(RecordingTelegram):
    """Delivers the first message to chat 111 and refuses the next ones while ``refuse`` is set."""

    refuse = True

    def send_message(self, chat_id: int, text: str) -> int:
        from collectors.alerts import TelegramError

        if self.refuse and chat_id == 111 and any(c == 111 for c, _ in self.messages):
            raise TelegramError("Too Many Requests: retry after 5")
        return super().send_message(chat_id, text)


def test_a_digest_refused_partway_resends_only_what_did_not_arrive(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, nine_ten = many_class_issues(40)
    tg = SecondPartRefusedTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg, now=lambda: nine_ten)
    n.digest_if_due()
    first = [t for c, t in tg.messages if c == 111]
    assert len(first) == 1 and 0 < first[0].count("<a href=") < 40
    tg.refuse = False
    later = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg,
                     now=lambda: nine_ten + timedelta(hours=2))
    assert later.digest_due()                                # part 2 still waits
    later.digest_if_due()
    to_p1 = [t for c, t in tg.messages if c == 111]
    assert len(to_p1) > 1
    assert sum(t.count("<a href=") for t in to_p1) == 40     # each notice once: none lost, none twice
    assert not later.digest_due()


def test_a_digest_refused_for_one_person_is_retried_for_that_person_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-not-real")
    s, nine_ten = many_class_issues(3)
    tg = PickyTelegram()
    n = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg, now=lambda: nine_ten)
    n.digest_if_due()
    assert [c for c, _ in tg.messages] == [222]              # p1 (111) refused, p2 (222) delivered
    later = Notifier(s, {**s.settings(), "telegram_dry_run": False}, telegram=tg,
                     now=lambda: nine_ten + timedelta(hours=2))
    tg.refuse = None
    assert later.digest_due()                                # p1 still waits for today's digest
    assert later.digest_if_due() == 1
    assert [c for c, _ in tg.messages] == [222, 111]         # p2 is not sent it twice
    assert sum(t.count("<a href=") for c, t in tg.messages if c == 111) == 3
    assert not later.digest_due()
