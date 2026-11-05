"""PHAROS — the Telegram steps email: who may get it, what it says, and that a preview never sends."""

from __future__ import annotations

import pytest

from collectors import telegram_steps_mail as m

SAMA = {"id": "p1", "full_name": "Sama Mosaad", "email": "sama.mosaad@satopharma.com", "active": True,
        "telegram_chat_id": None}


class FakeDb:
    def __init__(self, row):
        self.row = row
        self.params = None

    def fetchone(self, sql, params):
        self.params = params
        return self.row


class FakeSmtp:
    sent: list = []
    logins: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        FakeSmtp.logins.append((self.host, self.port, user))

    def send_message(self, msg):
        FakeSmtp.sent.append(msg)


@pytest.fixture(autouse=True)
def mailbox(monkeypatch):
    monkeypatch.setenv("PHAROS_IMAP_HOST", "imap.mail.yahoo.com")
    monkeypatch.setenv("PHAROS_IMAP_USER", "pharos@satopharma.com")
    monkeypatch.setenv("PHAROS_IMAP_PASSWORD", "app-password")
    monkeypatch.delenv("PHAROS_SMTP_HOST", raising=False)
    FakeSmtp.sent, FakeSmtp.logins = [], []


def test_sends_the_steps_to_an_unconnected_person(capsys):
    assert m.main(["--email", "Sama.Mosaad@satopharma.com", "--greeting", "Dr Sama", "--send"],
                  db=FakeDb(SAMA), smtp_factory=FakeSmtp) == 0
    assert FakeSmtp.logins == [("smtp.mail.yahoo.com", 465, "pharos@satopharma.com")]
    (msg,) = FakeSmtp.sent
    assert msg["To"] == "Sama Mosaad <sama.mosaad@satopharma.com>"
    assert msg["From"] == "PHAROS <pharos@satopharma.com>"
    body = msg.get_content()
    assert body.startswith("Dear Dr Sama,")
    assert "press Connect Telegram" in body and "https://pharos-satopharma.pages.dev" in body
    assert "Sent to Sama Mosaad" in capsys.readouterr().out


def test_a_preview_never_sends(capsys):
    assert m.main(["--email", "sama.mosaad@satopharma.com"], db=FakeDb(SAMA), smtp_factory=FakeSmtp) == 0
    assert FakeSmtp.sent == [] and FakeSmtp.logins == []
    out = capsys.readouterr().out
    assert "Dear Sama Mosaad," in out and "Not sent: preview only" in out


@pytest.mark.parametrize("row,why", [
    (None, "is not a PHAROS person"),
    ({**SAMA, "active": False}, "is not active"),
    ({**SAMA, "telegram_chat_id": 12345}, "already connected Telegram"),
])
def test_refuses_anyone_else(row, why, capsys):
    assert m.main(["--email", "sama.mosaad@satopharma.com", "--send"], db=FakeDb(row),
                  smtp_factory=FakeSmtp) == 2
    assert FakeSmtp.sent == []
    assert why in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["--email", "not an address", "--send"],
    ["--email", "sama.mosaad@satopharma.com", "--greeting", "Dr <b>Sama</b>", "--send"],
])
def test_refuses_a_bad_address_or_greeting(args):
    assert m.main(args, db=FakeDb(SAMA), smtp_factory=FakeSmtp) == 2
    assert FakeSmtp.sent == []
