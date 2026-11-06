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

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "imap-inbox"
EML = (FIXTURES / "fimea-newsletter.eml").read_bytes()
OTHER = (b"From: Someone <news@example.com>\r\nSubject: Not ours\r\n"
         b"Date: Tue, 03 Nov 2026 10:00:00 +0000\r\n\r\nhello\r\n")
ALLOW = {"fimea-email": ["fimea.fi"], "tga-email": ["tga.gov.au"]}
YAHOO = ["yahoo.com"]
# Constructed and DKIM-signed for these tests with a throwaway key (selector pharos-test); only its public
# half is kept, as the DNS record. Yahoo's IMAP gave GovDelivery's real FDA mail no Authentication-Results.
FDA_SIGNED = (FIXTURES / "fda-dkim-signed.eml").read_bytes()
FDA_DNS_TXT = (FIXTURES / "fda-dkim-dns.txt").read_bytes().strip()
FDA_ALLOW = {"fda-email": ["public.govdelivery.com"]}


def fda_dns(name, timeout=5):
    return FDA_DNS_TXT if name == b"pharos-test._domainkey.public.govdelivery.com." else None
# Anyone can write "From: …@fimea.fi", and Fimea's DMARC is p=none, so such a message is delivered. The
# forger may add a passing Authentication-Results of their own, but it sits BELOW the receiving server's
# real verdict, which here says the forged message failed.
FORGED = (b"Authentication-Results: atlas7.mail.bf1.yahoo.com; dkim=none; "
          b"spf=softfail smtp.mailfrom=evil.example; dmarc=fail(p=NONE) header.from=fimea.fi\r\n" + EML)


class FakeIMAP:
    """Just enough of imaplib.IMAP4 for collect(). Records every command. ``messages`` are the Inbox;
    ``folders`` adds other folders by their LIST line (flags, name) → their messages (uids kept distinct)."""

    def __init__(self, messages: dict[bytes, bytes],
                 folders: dict[tuple[str, str], dict[bytes, bytes]] | None = None) -> None:
        self.boxes = {"INBOX": messages, **{name: msgs for (_, name), msgs in (folders or {}).items()}}
        self.listing = [rb'(\HasNoChildren) "/" "Inbox"'] + [
            f'({flags}) "/" "{name}"'.encode() for (flags, name) in (folders or {})]
        self.messages = messages
        self.seen: set[bytes] = set()
        self.commands: list[tuple] = []
        self.logged_out = False

    def list(self):
        self.commands.append(("LIST",))
        return "OK", list(self.listing)

    def select(self, mailbox: str):
        self.commands.append(("SELECT", mailbox))
        name = mailbox.strip('"')
        if name not in self.boxes:
            return "NO", [b"no such folder"]
        self.messages = self.boxes[name]
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command: str, *args):
        self.commands.append((command, *args))
        if command == "SEARCH":
            unseen = [u for u in self.messages if u not in self.seen]
            return "OK", [b" ".join(unseen)]
        if command == "FETCH":
            uid, what = args
            raw = self.messages[uid]
            if "BODY.PEEK[HEADER]" in what:
                head = raw.replace(b"\r\n", b"\n").split(b"\n\n", 1)[0] + b"\n\n"
                return "OK", [(b"1 (UID " + uid + b")", head), b")"]
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
                                source_exists=lambda sid: True, authserv_domains=YAHOO)
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


def test_the_spam_folder_is_read_too_and_nothing_is_moved(tmp_path):
    # Yahoo files newsletters under "Bulk", flagged \Junk; TGA's and Fimea's first mails may sit there.
    server = FakeIMAP({b"8": OTHER}, folders={(r"\Junk \HasNoChildren", "Bulk"): {b"21": EML},
                                              (r"\Sent", "Sent"): {b"31": EML}})
    rows: list[dict] = []
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), ALLOW, connect=lambda: server,
                                insert=rows.append, source_exists=lambda sid: True, authserv_domains=YAHOO)
    assert counts == {"fimea-email": 1, "tga-email": 0}
    assert [c[1] for c in server.commands if c[0] == "SELECT"] == ["INBOX", "Bulk"]   # never Sent
    assert server.seen == {b"21"} and rows[0]["subject"] == "Lääketurvallisuustiedote: lornoksikaami"
    assert {c[0] for c in server.commands} <= {"LIST", "SELECT", "SEARCH", "FETCH", "STORE"}  # no MOVE, no EXPUNGE


def test_the_spam_folder_is_found_by_its_flag_else_by_name():
    flagged = FakeIMAP({}, folders={(r"\HasNoChildren", "Spam"): {}, (r"\Junk", "Bulk Mail"): {}})
    assert imap_inbox.junk_folders(flagged) == ["Bulk Mail"]
    named = FakeIMAP({}, folders={(r"\HasNoChildren", "Bulk"): {}, (r"\Noselect", "Junk"): {},
                                  (r"\Drafts", "Drafts"): {}})
    assert imap_inbox.junk_folders(named) == ["Bulk"]
    assert imap_inbox.junk_folders(FakeIMAP({})) == []
    assert imap_inbox._quoted("Bulk Mail") == '"Bulk Mail"' and imap_inbox._quoted("Bulk") == "Bulk"


def test_a_spam_folder_that_will_not_open_leaves_the_inbox_read(tmp_path):
    server = FakeIMAP({b"7": EML})
    server.listing.append(rb'(\Junk) "/" "Gone"')                  # listed, but SELECT says NO
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), ALLOW, connect=lambda: server,
                                insert=lambda row: None, source_exists=lambda sid: True,
                                authserv_domains=YAHOO)
    assert counts["fimea-email"] == 1 and server.seen == {b"7"}


def test_missing_source_row_leaves_mail_unread(tmp_path):
    server = FakeIMAP({b"7": EML})
    rows: list[dict] = []
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), ALLOW, connect=lambda: server,
                                insert=rows.append, source_exists=lambda sid: False,
                                authserv_domains=YAHOO)
    assert counts["fimea-email"] == 0 and rows == [] and server.seen == set()


def test_forged_sender_is_held_unread(tmp_path):
    server = FakeIMAP({b"7": FORGED})
    rows: list[dict] = []
    held: dict[str, int] = {}
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), ALLOW, connect=lambda: server,
                                insert=rows.append, source_exists=lambda sid: True,
                                authserv_domains=YAHOO, held=held)
    assert counts["fimea-email"] == 0 and rows == [] and server.seen == set()
    assert held == {"fimea-email": 1}
    assert not any(c[0] == "FETCH" and "BODY.PEEK[]" in c[2] for c in server.commands)


def test_sender_verdict_rules():
    ok = (b"Authentication-Results: atlas1.mail.yahoo.com; dkim=pass header.i=@news.fimea.fi; "
          b"spf=none\r\nFrom: x@fimea.fi\r\n\r\n")
    assert imap_inbox.sender_verified(ok, ["fimea.fi"], YAHOO)
    # a pass for another domain (the forger's own) proves nothing about fimea.fi
    other = ok.replace(b"@news.fimea.fi", b"@fimea.fi.evil.example")
    assert not imap_inbox.sender_verified(other, ["fimea.fi"], YAHOO)
    # a verdict written by a server we do not trust is ignored
    untrusted = ok.replace(b"atlas1.mail.yahoo.com", b"mx.evil.example")
    assert not imap_inbox.sender_verified(untrusted, ["fimea.fi"], YAHOO)
    # no verdict at all → held
    assert not imap_inbox.sender_verified(b"From: x@fimea.fi\r\n\r\n", ["fimea.fi"], YAHOO)
    # the IMAP host decides whose verdicts count when nothing else is set
    assert imap_inbox.trusted_authserv_domains() == []


def test_bodies_are_capped():
    big = EML.replace(b"CONSTRUCTED TEST MESSAGE", b"A" * (imap_inbox.MAX_BODY_CHARS + 10), 1)
    assert len(imap_inbox.parse_message(big).text_body) == imap_inbox.MAX_BODY_CHARS


def test_not_configured_raises_quietly():
    with pytest.raises(RuntimeError, match=imap_inbox.NOT_CONFIGURED):
        imap_inbox.collect(types.SimpleNamespace(db=None), ALLOW)


def test_runner_notes_imap_not_configured(tmp_path):
    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    _, sources, _ = load_catalogue()
    mail_sources = [s for s in sources if s.parser == "email_inbox"]
    mail_ids = {"fimea-email", "tga-email", "fda-email", "famhp-email", "hc-email"}
    assert {s.id for s in mail_sources} == mail_ids
    empty = types.SimpleNamespace(STRUCTURED_FIELDS=[], list_items=lambda ctx, src: [])
    ctx = types.SimpleNamespace(db=None, run_id=store.create_run("manual", None), first_status=None,
                                begin_source=lambda: None, archiver=Archive(tmp_path / "a"))
    runner = Runner(store, ctx, Notifier(store, store.settings()), store.settings(),
                    parser_loader=lambda name: empty)
    assert runner.run(mail_sources)                  # not configured is not a failure
    errors = {r["source_id"]: r["error"] for r in store.source_run.values()}
    assert errors == dict.fromkeys(mail_ids, "imap not configured")


def test_fda_and_famhp_mail_reach_their_own_sources():
    _, sources, _ = load_catalogue()
    allow = {s.id: s.options["from_domains"] for s in sources if s.parser == "email_inbox"}

    def owner(domain):
        return {sid for sid, doms in allow.items() if imap_inbox.domain_matches(domain, doms)}

    assert owner("public.govdelivery.com") == {"fda-email"}     # the MedWatch e-mail list
    assert owner("info.fda.gov") == {"fda-email"}
    assert owner("afmps.be") == {"famhp-email"} and owner("fagg-afmps.be") == {"famhp-email"}
    assert owner("health.gov.au") == {"tga-email"} and owner("fimea.fi") == {"fimea-email"}
    assert owner("canada.ca") == {"hc-email"} and owner("hc-sc.gc.ca") == {"hc-email"}   # MedEffect e-Notice


def test_held_mail_log_names_the_servers_verdicts_without_addresses():
    from collectors.core.imap_inbox import auth_summary
    hdr = (b"Authentication-Results: mta.yahoo.com;\r\n dkim=pass header.i=@public.govdelivery.com;\r\n"
           b" dmarc=pass(p=NONE) header.from=public.govdelivery.com;\r\n"
           b"From: FDA <usfda@public.govdelivery.com>\r\n\r\n")
    got = auth_summary(hdr)
    assert got.startswith("mta.yahoo.com (1 header(s)):")
    assert "dkim=pass(public.govdelivery.com)" in got and "dmarc=pass(public.govdelivery.com)" in got
    assert "usfda@" not in got
    assert auth_summary(b"From: FDA <usfda@public.govdelivery.com>\r\n\r\n") == "no Authentication-Results header"


def test_no_server_verdict_accepts_a_valid_dkim_signature_from_the_sender(tmp_path):
    server = FakeIMAP({b"10": FDA_SIGNED})
    rows: list[dict] = []
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), FDA_ALLOW, connect=lambda: server,
                                insert=rows.append, source_exists=lambda sid: True,
                                authserv_domains=YAHOO, dkim_dns=fda_dns)
    assert counts == {"fda-email": 1} and server.seen == {b"10"}
    assert rows[0]["from_addr"] == "usfda@public.govdelivery.com"


def test_no_server_verdict_and_no_valid_signature_is_held(tmp_path):
    tampered = FDA_SIGNED.replace(b"The FDA did not send it.", b"The FDA sent it.")
    unsigned = FDA_SIGNED[FDA_SIGNED.index(b"From: "):]
    for raw in (tampered, unsigned):
        server = FakeIMAP({b"10": raw})
        held: dict[str, int] = {}
        counts = imap_inbox.collect(ctx_with_archive(tmp_path), FDA_ALLOW, connect=lambda s=server: s,
                                    insert=lambda row: None, source_exists=lambda sid: True,
                                    authserv_domains=YAHOO, held=held, dkim_dns=fda_dns)
        assert counts == {"fda-email": 0} and held == {"fda-email": 1} and server.seen == set()


def test_valid_dkim_from_another_domain_proves_nothing():
    assert imap_inbox.dkim_verified(FDA_SIGNED, ["public.govdelivery.com"], fda_dns) == "public.govdelivery.com"
    assert imap_inbox.dkim_verified(FDA_SIGNED, ["fda.gov"], fda_dns) is None


def test_a_failing_server_verdict_is_never_overridden_by_our_own_check(tmp_path):
    failing = (b"Authentication-Results: atlas7.mail.bf1.yahoo.com; dkim=fail; spf=softfail "
               b"smtp.mailfrom=evil.example; dmarc=fail(p=NONE) header.from=public.govdelivery.com\r\n"
               + FDA_SIGNED)
    server = FakeIMAP({b"10": failing})
    held: dict[str, int] = {}
    counts = imap_inbox.collect(ctx_with_archive(tmp_path), FDA_ALLOW, connect=lambda: server,
                                insert=lambda row: None, source_exists=lambda sid: True,
                                authserv_domains=YAHOO, held=held, dkim_dns=fda_dns)
    assert counts == {"fda-email": 0} and held == {"fda-email": 1}
    assert not any(c[0] == "FETCH" and "BODY.PEEK[]" in c[2] for c in server.commands)


def test_a_verdict_the_sender_wrote_below_the_servers_entry_hop_is_not_the_servers():
    forged = (b"Received: from 10.217.150.27 by atlas1.mail.bf1.yahoo.com with HTTP; Tue, 3 Nov 2026\r\n"
              b"Received: from 127.0.0.1 (EHLO evil.example) (93.184.216.34) by 10.217.150.27 with SMTPs;"
              b" Tue, 3 Nov 2026\r\n"
              b"Authentication-Results: atlas1.mail.yahoo.com; dmarc=pass header.from=fimea.fi\r\n"
              b"From: x@fimea.fi\r\n\r\n")
    assert not imap_inbox.sender_verified(forged, ["fimea.fi"], YAHOO)
    assert not imap_inbox.has_trusted_verdict(forged, YAHOO)   # so the own DKIM check decides
    # the same verdict written by the server itself, above the hop where the message came in
    real = (b"Received: from 10.217.150.27 by atlas1.mail.bf1.yahoo.com with HTTP; Tue, 3 Nov 2026\r\n"
            b"Authentication-Results: atlas1.mail.yahoo.com; dmarc=pass header.from=fimea.fi\r\n"
            b"Received: from 127.0.0.1 (EHLO mail.fimea.fi) (193.166.1.10) by 10.217.150.27 with SMTPs;"
            b" Tue, 3 Nov 2026\r\n"
            b"From: x@fimea.fi\r\n\r\n")
    assert imap_inbox.sender_verified(real, ["fimea.fi"], YAHOO)


def test_a_mail_source_with_nothing_received_is_flagged_once_after_its_gap(tmp_path):
    # TGA's and Fimea's mail sources read as working for days with nothing in them (6 Nov 2026). A mail source
    # waits from the day it was added; past its expected gap it turns to "check it", with one alert.
    from datetime import timedelta

    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    _, sources, _ = load_catalogue()
    tga, fimea = (next(s for s in sources if s.id == sid) for sid in ("tga-email", "fimea-email"))
    now = datetime.now(timezone.utc)
    store.source["tga-email"]["created_at"] = now - timedelta(days=tga.expected_max_gap_days + 1)
    store.source["fimea-email"]["created_at"] = now - timedelta(days=1)
    empty = types.SimpleNamespace(STRUCTURED_FIELDS=[], list_items=lambda ctx, src: [])
    alerts: list[tuple] = []
    notifier = types.SimpleNamespace(health_alert=lambda *a: alerts.append(a), issue_alert=lambda i: None)

    def run():
        ctx = types.SimpleNamespace(db=None, run_id=store.create_run("manual", None), first_status=None,
                                    begin_source=lambda: None, archiver=Archive(tmp_path / "a"))
        Runner(store, ctx, notifier, store.settings(), parser_loader=lambda name: empty).run([tga, fimea])

    run()
    assert store.source["tga-email"]["health"] == "degraded"
    assert store.source["fimea-email"]["health"] == "ok"           # still within its gap: waiting
    assert [a[:2] for a in alerts] == [("tga-email", "degraded")]
    run()
    assert len(alerts) == 1                                          # one alert, not one per run
