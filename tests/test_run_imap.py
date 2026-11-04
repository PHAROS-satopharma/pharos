"""The PHAROS mailbox reader with a fake IMAP server. The one message used is constructed
(tests/fixtures/imap-inbox/README.md). No network, no mail is sent."""

from __future__ import annotations

import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collectors.alerts import Notifier
from collectors.core import imap_inbox
from collectors.core.archive import Archive
from collectors.core.memstore import MemoryStore
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.run import Runner

EML = (Path(__file__).resolve().parent / "fixtures" / "imap-inbox" / "fimea-newsletter.eml").read_bytes()
OTHER = (b"From: Someone <news@example.com>\r\nSubject: Not ours\r\n"
         b"Date: Tue, 03 Nov 2026 10:00:00 +0000\r\n\r\nhello\r\n")
ALLOW = {"fimea-email": ["fimea.fi"], "tga-email": ["tga.gov.au"]}


class FakeIMAP:
    """Just enough of imaplib.IMAP4 for collect(). Records every command."""

    def __init__(self, messages: dict[bytes, bytes]) -> None:
        self.messages = messages
        self.seen: set[bytes] = set()
        self.commands: list[tuple] = []
        self.logged_out = False

    def select(self, mailbox: str):
        self.commands.append(("SELECT", mailbox))
        return "OK", [b"2"]

    def uid(self, command: str, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            unseen = [u for u in self.messages if u not in self.seen]
            return "OK", [b" ".join(unseen)]
        if command == "FETCH":
            uid, what = args
            raw = self.messages[uid]
            if "HEADER.FIELDS (FROM)" in what:
                head = next(line for line in raw.splitlines() if line.lower().startswith(b"from:"))
                return "OK", [(b"1 (UID " + uid + b")", head + b"\r\n\r\n"), b")"]
            assert "BODY.PEEK[]" in what          # never a plain BODY[] fetch (that marks Seen)
            return "OK", [(b"1 (UID " + uid + b")", raw), b")"]
        if command == "STORE":
            uid, op, flags = args
            assert op == "+FLAGS" and flags == "(\\Seen)"
            self.seen.add(uid)
            return "OK", [b""]
        raise AssertionError(f"unexpected IMAP command {command}")

    def logout(self):
        self.logged_out = True
        return "BYE", [b""]


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("PHAROS_IMAP_HOST", "PHAROS_IMAP_PORT", "PHAROS_IMAP_USER", "PHAROS_IMAP_PASSWORD",
                "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET",
                "TELEGRAM_BOT_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


def ctx_with_archive(tmp_path):
    return types.SimpleNamespace(db=None, archiver=Archive(tmp_path / "archive"))


def test_parse_constructed_message():
    p = imap_inbox.parse_message(EML)
    assert p.from_addr == "uutiskirje@fimea.fi" and p.from_domain == "fimea.fi"
    assert p.subject == "Lääketurvallisuustiedote: lornoksikaami"
    assert p.received_at == datetime(2026, 11, 3, 7, 15, tzinfo=timezone.utc)
    assert "Lornoksikaamia sisältävien" in p.text_body
    assert "<p>" in p.html_body


def test_domain_allow_list():
    assert imap_inbox.domain_matches("fimea.fi", ["fimea.fi"])
    assert imap_inbox.domain_matches("news.fimea.fi", ["fimea.fi"])
    assert not imap_inbox.domain_matches("notfimea.fi", ["fimea.fi"])
    assert not imap_inbox.domain_matches("fimea.fi.evil.example", ["fimea.fi"])


def test_eml_key_shape():
    key = imap_inbox.eml_key(datetime(2026, 11, 3, 23, 30, tzinfo=timezone.utc))
    assert key.startswith("inbound/2026-11-03/") and key.endswith(".eml") and len(key) == 59


def test_collect_reads_only_allowed_unseen_mail(tmp_path):
    server = FakeIMAP({b"7": EML, b"8": OTHER})
    rows: list[dict] = []
    ctx = ctx_with_archive(tmp_path)
    counts = imap_inbox.collect(ctx, ALLOW, connect=lambda: server, insert=rows.append,
                                source_exists=lambda sid: True)
    assert counts == {"fimea-email": 1, "tga-email": 0}
    assert server.seen == {b"7"}                     # the other message stays unread
    assert not any(c[0] == "FETCH" and c[1] == b"8" and "BODY.PEEK[]" in c[2] for c in server.commands)
    assert server.logged_out
    (row,) = rows
    assert row["source_id"] == "fimea-email" and row["from_addr"] == "uutiskirje@fimea.fi"
    assert row["r2_key"].startswith("inbound/2026-11-03/") and row["r2_key"].endswith(".eml")
    assert (tmp_path / "archive" / row["r2_key"]).read_bytes() == EML   # the raw message, unchanged
    # archived and inserted before it is marked Seen
    store_at = next(k for k, c in enumerate(server.commands) if c[0] == "STORE")
    body_at = next(k for k, c in enumerate(server.commands) if c[0] == "FETCH" and "BODY.PEEK[]" in c[2])
    assert body_at < store_at


def test_missing_source_row_leaves_mail_unread(tmp_path):
    server = FakeIMAP({b"7": EML})
    rows: list[dict] = []
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), ALLOW, connect=lambda: server,
                                insert=rows.append, source_exists=lambda sid: False)
    assert counts["fimea-email"] == 0 and rows == [] and server.seen == set()


def test_not_configured_raises_quietly():
    with pytest.raises(RuntimeError, match=imap_inbox.NOT_CONFIGURED):
        imap_inbox.collect(types.SimpleNamespace(db=None), ALLOW)


def test_runner_notes_imap_not_configured(tmp_path):
    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    _, sources, _ = load_catalogue()
    mail_sources = [s for s in sources if s.parser == "email_inbox"]
    assert {s.id for s in mail_sources} == {"fimea-email", "tga-email"}
    empty = types.SimpleNamespace(STRUCTURED_FIELDS=[], list_items=lambda ctx, src: [])
    ctx = types.SimpleNamespace(db=None, run_id=store.create_run("manual", None), first_status=None,
                                begin_source=lambda: None, archiver=Archive(tmp_path / "a"))
    runner = Runner(store, ctx, Notifier(store, store.settings()), store.settings(),
                    parser_loader=lambda name: empty)
    assert runner.run(mail_sources)                  # not configured is not a failure
    errors = {r["source_id"]: r["error"] for r in store.source_run.values()}
    assert errors == {"fimea-email": "imap not configured", "tga-email": "imap not configured"}
