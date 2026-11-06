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


def test_workflow_runs_only_on_main():
    # A run started on a branch must not send real email with the production secrets.
    import pathlib

    import yaml

    wf = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/telegram-steps-mail.yml"
    job = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["mail"]
    assert job.get("if") == "github.ref == 'refs/heads/main'"
    for step in job["steps"]:
        # A step's env is printed at the head of its log, and the run logs are public.
        assert "inputs." not in str(step.get("env", {})) and "inputs." not in str(step.get("run", ""))
    assert any("--from-event" in str(step.get("run", "")) for step in job["steps"])


def _event(tmp_path, **inputs):
    import json

    path = tmp_path / "event.json"
    path.write_text(json.dumps({"inputs": inputs}), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("send", [True, "true"])
def test_from_the_event_file_it_sends_and_the_log_names_nobody(tmp_path, capsys, send):
    ev = _event(tmp_path, email="Sama.Mosaad@satopharma.com", greeting="Dr Sama", send=send)
    assert m.main(["--from-event", ev], db=FakeDb(SAMA), smtp_factory=FakeSmtp) == 0
    (msg,) = FakeSmtp.sent
    assert msg["To"] == "Sama Mosaad <sama.mosaad@satopharma.com>" and "Dear Dr Sama," in msg.get_content()
    out = capsys.readouterr()
    log = (out.out + out.err).lower()
    assert "sent, message-id" in log
    for private in ("sama", "mosaad", "sama.mosaad@"):
        assert private not in log


def test_from_the_event_file_a_preview_never_sends_and_names_nobody(tmp_path, capsys):
    ev = _event(tmp_path, email="sama.mosaad@satopharma.com", greeting="Dr Sama", send=False)
    assert m.main(["--from-event", ev], db=FakeDb(SAMA), smtp_factory=FakeSmtp) == 0
    assert FakeSmtp.sent == []
    out = capsys.readouterr().out.lower()
    assert "preview only" in out and "sama" not in out and "dear" not in out


@pytest.mark.parametrize("row", [None, {**SAMA, "active": False}, {**SAMA, "telegram_chat_id": 7}])
def test_from_the_event_file_a_refusal_names_nobody(tmp_path, capsys, row):
    ev = _event(tmp_path, email="sama.mosaad@satopharma.com", greeting="", send=True)
    assert m.main(["--from-event", ev], db=FakeDb(row), smtp_factory=FakeSmtp) == 2
    err = capsys.readouterr().err.lower()
    assert "not sent" in err and "sama" not in err
