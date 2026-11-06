"""PHAROS — a written message from the bot: who may get it, that the text goes as written, that a preview never
sends, and that every send is recorded. Nothing here can reach Telegram: the client is a recording stub."""

from __future__ import annotations

import pytest

from collectors import telegram_note as m
from collectors.alerts import TelegramError

SAMA = {"id": "p1", "full_name": "Sama Mosaad", "email": "sama.mosaad@satopharma.com", "active": True,
        "telegram_chat_id": 555}


class FakeDb:
    def __init__(self, row):
        self.row = row
        self.inserts: list[dict] = []

    def fetchone(self, sql, params):
        return self.row

    def execute(self, sql, params):
        assert "insert into notification" in sql
        self.inserts.append(params)


class RecordingTelegram:
    def __init__(self, fail: bool = False) -> None:
        self.messages: list[tuple[int, str]] = []
        self.fail = fail

    def send_message(self, chat_id: int, text: str) -> int:
        if self.fail:
            raise TelegramError("sendMessage: Forbidden: bot was blocked by the user")
        self.messages.append((chat_id, text))
        return 4242


@pytest.fixture(autouse=True)
def no_real_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("MESSAGE", "Adding the Japan code\n1. Open PHAROS → Ingredients.\n2. Type 6241013 & <Save>.")


def test_sends_the_text_as_written_and_records_it(capsys):
    db, tg = FakeDb(SAMA), RecordingTelegram()
    assert m.main(["--email", "Sama.Mosaad@satopharma.com", "--send"], db=db, telegram=tg) == 0
    ((chat, text),) = tg.messages
    assert chat == 555
    assert text == "Adding the Japan code\n1. Open PHAROS → Ingredients.\n2. Type 6241013 &amp; &lt;Save&gt;."
    (row,) = db.inserts
    assert row == {"p": "p1", "m": 4242, "e": None, "s": text}
    assert "Sent to Sama Mosaad" in capsys.readouterr().out


def test_a_preview_never_sends():
    db, tg = FakeDb(SAMA), RecordingTelegram()
    assert m.main(["--email", "sama.mosaad@satopharma.com"], db=db, telegram=tg) == 0
    assert tg.messages == [] and db.inserts == []


def test_a_refusal_by_telegram_is_recorded():
    db = FakeDb(SAMA)
    assert m.main(["--email", "sama.mosaad@satopharma.com", "--send"], db=db,
                  telegram=RecordingTelegram(fail=True)) == 1
    (row,) = db.inserts
    assert row["m"] is None and "blocked" in row["e"]


@pytest.mark.parametrize("row,why", [
    (None, "is not a PHAROS person"),
    ({**SAMA, "active": False}, "is not active"),
    ({**SAMA, "telegram_chat_id": None}, "has not connected Telegram"),
])
def test_refuses_anyone_else(row, why, capsys):
    db, tg = FakeDb(row), RecordingTelegram()
    assert m.main(["--email", "sama.mosaad@satopharma.com", "--send"], db=db, telegram=tg) == 2
    assert tg.messages == [] and db.inserts == []
    assert why in capsys.readouterr().err


@pytest.mark.parametrize("text,why", [("   ", "is empty"), ("x" * 4001, "at most 4000")])
def test_refuses_an_empty_or_too_long_message(monkeypatch, text, why, capsys):
    monkeypatch.setenv("MESSAGE", text)
    tg = RecordingTelegram()
    assert m.main(["--email", "sama.mosaad@satopharma.com", "--send"], db=FakeDb(SAMA), telegram=tg) == 2
    assert tg.messages == []
    assert why in capsys.readouterr().err


# The repository and its run logs are public: the workflow reads what was typed from the event file, and the
# log never names the person, their address or the text.

def _event(tmp_path, **inputs):
    import json

    path = tmp_path / "event.json"
    path.write_text(json.dumps({"inputs": inputs}), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("send", [True, "true"])
def test_from_the_event_file_it_sends_and_the_log_names_nobody(tmp_path, monkeypatch, capsys, send):
    monkeypatch.delenv("MESSAGE")
    db, tg = FakeDb(SAMA), RecordingTelegram()
    ev = _event(tmp_path, email="Sama.Mosaad@satopharma.com", message="Your weekly report is ready", send=send)
    assert m.main(["--from-event", ev], db=db, telegram=tg) == 0
    assert tg.messages == [(555, "Your weekly report is ready")] and len(db.inserts) == 1
    out = capsys.readouterr()
    log = (out.out + out.err).lower()
    assert "sent on telegram" in log
    for private in ("sama", "mosaad", "satopharma", "weekly report"):
        assert private not in log


def test_from_the_event_file_a_preview_never_sends_and_names_nobody(tmp_path, capsys):
    db, tg = FakeDb(SAMA), RecordingTelegram()
    ev = _event(tmp_path, email="sama.mosaad@satopharma.com", message="Your weekly report is ready", send=False)
    assert m.main(["--from-event", ev], db=db, telegram=tg) == 0
    assert tg.messages == [] and db.inserts == []
    out = capsys.readouterr().out.lower()
    assert "preview only" in out
    for private in ("sama", "mosaad", "satopharma", "weekly report"):
        assert private not in out


@pytest.mark.parametrize("row", [None, {**SAMA, "active": False}, {**SAMA, "telegram_chat_id": None}])
def test_from_the_event_file_a_refusal_names_nobody(tmp_path, capsys, row):
    ev = _event(tmp_path, email="sama.mosaad@satopharma.com", message="hello", send=True)
    assert m.main(["--from-event", ev], db=FakeDb(row), telegram=RecordingTelegram()) == 2
    err = capsys.readouterr().err.lower()
    assert "not sent" in err and "sama" not in err and "satopharma" not in err


def test_workflow_passes_no_input_through_the_log():
    # A step's env is printed at the head of its log; an input there would be public.
    import pathlib

    import yaml

    wf = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/telegram-note.yml"
    job = yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"]["note"]
    assert job.get("if") == "github.ref == 'refs/heads/main'"
    for step in job["steps"]:
        assert "inputs." not in str(step.get("env", {})) and "inputs." not in str(step.get("run", ""))
    assert any("--from-event" in str(step.get("run", "")) for step in job["steps"])
