"""Read the PHAROS mailbox (pharos@satopharma.com) over IMAP into ``inbound_email``.

The mailbox subscribes to newsletters (Fimea, TGA) whose web pages cannot be read directly. On each
4h run, before the ``email_inbox`` sources, the Inbox and the spam folder are read (Yahoo files
newsletters under "Bulk"; the folder is found by its IMAP Junk flag, else by name). Every UNSEEN
message whose From domain is on a source's allow-list (``options.from_domains`` in sources.yaml) is
archived as raw ``message/rfc822`` under ``inbound/<YYYY-MM-DD>/<uuid>.eml``, written
to ``inbound_email`` and only then marked Seen. Other mail is never touched (read with BODY.PEEK).
Never sends mail.

The From line can be forged by anyone, and Fimea publishes DMARC p=none, so a From domain alone proves
nothing. A message is accepted only when the receiving mail server's own verdict (the TOPMOST
Authentication-Results header, written by a server under the IMAP host's domain) shows DMARC, DKIM or SPF
passing for one of that source's allowed domains. Yahoo's IMAP server hands some messages over with
no Authentication-Results at all (GovDelivery's FDA mail on 5 Nov 2026, although Yahoo's web view shows
one); for those only, PHAROS checks the DKIM signature itself against the signer's DNS key and accepts a
valid one from an allowed domain (``dkim_verified``). A server verdict that is present and not passing is
never overridden. An Authentication-Results header that sits below the hop where the message entered the
receiving server (the topmost Received line naming a public address) came with the message, so the sender
wrote it: it is never the server's verdict, whatever server name it carries. Anything else is held: left
unread, counted, and reported in the screening log. Bodies are capped so no message can fill the database.

Environment: ``PHAROS_IMAP_HOST``, ``PHAROS_IMAP_PORT`` (993, SSL), ``PHAROS_IMAP_USER``,
``PHAROS_IMAP_PASSWORD``. Absent → skipped, and the caller records 'imap not configured'.
"""

from __future__ import annotations

import email
import imaplib
import ipaddress
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

NOT_CONFIGURED = "imap not configured"
MAX_RAW_BYTES = 10 * 1024 * 1024   # a bigger message is held, never archived
MAX_BODY_CHARS = 500_000           # per text/html body stored in the database

_AR_RESULT = re.compile(r"(?<![\w.-])(dmarc|dkim|spf)\s*=\s*([a-z]+)", re.I)
_DKIM_D = re.compile(r"(?:^|;)\s*d\s*=\s*([^;\s]+)", re.I)
_AR_PROP = re.compile(r"(?<![\w.-])(header\.d|header\.i|header\.from|smtp\.mailfrom)\s*=\s*([^\s;()]+)",
                      re.I)
_IP_LITERAL = re.compile(r"[\[(](?:IPv6:)?([0-9A-Fa-f:.]{3,})[\])]")
_LIST_LINE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>"(?:[^"\\]|\\.)*"|\S+)\s*$', re.I)
_SPAM_NAMES = ("bulk", "bulk mail", "junk", "junk e-mail", "junk email", "spam")


@dataclass
class ParsedEmail:
    from_addr: str
    from_domain: str
    subject: str
    received_at: datetime
    text_body: str | None
    html_body: str | None


def domain_matches(domain: str, allowed: Iterable[str]) -> bool:
    domain = domain.lower().strip(".")
    for a in allowed:
        a = a.lower().strip(".")
        if domain == a or domain.endswith("." + a):
            return True
    return False


def trusted_authserv_domains() -> list[str]:
    """Servers whose Authentication-Results we believe: PHAROS_IMAP_AUTHSERV_DOMAINS (comma list), or the
    parent domain of the IMAP host (imap.mail.yahoo.com → yahoo.com)."""
    env = os.environ.get("PHAROS_IMAP_AUTHSERV_DOMAINS")
    if env:
        return [d.strip().lower() for d in env.split(",") if d.strip()]
    host = (os.environ.get("PHAROS_IMAP_HOST") or "").lower().strip(".")
    return [".".join(host.split(".")[-2:])] if host.count(".") >= 1 else []


def _domain_of(value: str) -> str:
    value = value.strip().strip("<>\"").lower()
    return value.rsplit("@", 1)[-1] if "@" in value else value


def _from_public_address(received: str) -> bool:
    """True when a Received line's from-part records a public address: the hop where the message came
    in from outside (the receiving server's own internal hops record private ones)."""
    for m in _IP_LITERAL.finditer(received.split(" by ", 1)[0]):
        try:
            if ipaddress.ip_address(m.group(1)).is_global:
                return True
        except ValueError:
            continue
    return False


def _server_results(raw_headers: bytes) -> str:
    """The topmost Authentication-Results, or '' when there is none or it sits below the hop where the
    message entered the receiving server (then the sender wrote it)."""
    headers = [(k.lower(), " ".join(str(v).split()))
               for k, v in email.message_from_bytes(raw_headers).items()]
    top = next((i for i, (k, _) in enumerate(headers) if k == "authentication-results"), None)
    if top is None:
        return ""
    entry = next((i for i, (k, v) in enumerate(headers)
                  if k == "received" and _from_public_address(v)), None)
    return "" if entry is not None and top > entry else headers[top][1]


def sender_verified(raw_headers: bytes, allowed: Iterable[str],
                    authserv_domains: Iterable[str]) -> bool:
    """True when the topmost Authentication-Results, written by a trusted server, shows DMARC, DKIM or
    SPF passing for an allowed domain."""
    top = _server_results(raw_headers)              # the receiving server's own header comes first
    if not top:
        return False
    authserv = top.split(";", 1)[0].strip().split()[0].lower() if top.strip() else ""
    if not domain_matches(authserv, list(authserv_domains)):
        return False
    allowed = list(allowed)
    for clause in top.split(";")[1:]:
        m = _AR_RESULT.search(clause)
        if not m or m.group(2).lower() != "pass":
            continue
        props = {k.lower(): _domain_of(v) for k, v in _AR_PROP.findall(clause)}
        method = m.group(1).lower()
        keys = {"dmarc": ("header.from",), "dkim": ("header.d", "header.i"),
                "spf": ("smtp.mailfrom",)}[method]
        if any(props.get(k) and domain_matches(props[k], allowed) for k in keys):
            return True
    return False


def has_trusted_verdict(raw_headers: bytes, authserv_domains: Iterable[str]) -> bool:
    """True when the topmost Authentication-Results was written by a trusted server (whatever it says)."""
    top = _server_results(raw_headers)
    authserv = top.split(";", 1)[0].strip().split()[0].lower() if top.strip() else ""
    return bool(authserv) and domain_matches(authserv, list(authserv_domains))


def dkim_verified(raw: bytes, allowed: Iterable[str],
                  dnsfunc: Callable[..., bytes | None] | None = None) -> str | None:
    """Our own DKIM check of the whole message: the signing domain (d=) of the first signature that is
    from an allowed domain and verifies against its published DNS key, else None."""
    import dkim

    allowed = list(allowed)
    for idx, sig in enumerate(email.message_from_bytes(raw).get_all("DKIM-Signature") or []):
        m = _DKIM_D.search(" ".join(str(sig).split()))
        if not m or not domain_matches(m.group(1).lower(), allowed):
            continue
        kwargs = {"dnsfunc": dnsfunc} if dnsfunc is not None else {}
        try:
            if dkim.DKIM(raw).verify(idx=idx, **kwargs):
                return m.group(1).lower()
        except Exception:  # noqa: BLE001 - a bad signature or DNS failure is simply "not verified"
            continue
    return None


def auth_summary(raw_headers: bytes) -> str:
    """Why a sender was not verified, for the log: the receiving server's name and its verdicts
    (``mta.yahoo.com: dkim=pass(public.govdelivery.com) spf=pass(…)``). No addresses, only domains."""
    results = email.message_from_bytes(raw_headers).get_all("Authentication-Results") or []
    if not results:
        return "no Authentication-Results header"
    top = " ".join(str(results[0]).split())
    authserv = top.split(";", 1)[0].strip().split()[0].lower() if top.strip() else "?"
    verdicts = []
    for clause in top.split(";")[1:]:
        m = _AR_RESULT.search(clause)
        if m:
            doms = sorted({_domain_of(v) for _, v in _AR_PROP.findall(clause)})
            verdicts.append(f"{m.group(1).lower()}={m.group(2).lower()}({','.join(doms)})")
    return f"{authserv} ({len(results)} header(s)): {' '.join(verdicts) or 'no verdicts'}"


def parse_message(raw: bytes) -> ParsedEmail:
    msg: EmailMessage = email.message_from_bytes(raw, policy=policy.default)  # type: ignore[assignment]
    _, addr = parseaddr(str(msg.get("From", "")))
    addr = addr.strip()
    domain = addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""
    try:
        received = parsedate_to_datetime(str(msg.get("Date")))
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    text_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    return ParsedEmail(
        from_addr=addr, from_domain=domain, subject=str(msg.get("Subject", "")).strip(),
        received_at=received,
        text_body=text_part.get_content()[:MAX_BODY_CHARS] if text_part is not None else None,
        html_body=html_part.get_content()[:MAX_BODY_CHARS] if html_part is not None else None,
    )


def imap_configured() -> bool:
    return all(os.environ.get(k) for k in ("PHAROS_IMAP_HOST", "PHAROS_IMAP_USER",
                                           "PHAROS_IMAP_PASSWORD"))


def _connect() -> imaplib.IMAP4:
    host = os.environ["PHAROS_IMAP_HOST"]
    port = int(os.environ.get("PHAROS_IMAP_PORT") or 993)
    conn = imaplib.IMAP4_SSL(host, port, timeout=60)
    conn.login(os.environ["PHAROS_IMAP_USER"], os.environ["PHAROS_IMAP_PASSWORD"])
    return conn


def junk_folders(conn: Any) -> list[str]:
    """The spam folder(s) of the mailbox: those LISTed with the Junk special-use flag, else those named
    like one (Bulk, Junk, Spam). Never the Inbox. A server that cannot LIST gives none."""
    try:
        status, lines = conn.list()
    except Exception:  # noqa: BLE001 - no folder list: the Inbox alone is read
        return []
    if status != "OK":
        return []
    flagged, named = [], []
    for line in lines or []:
        if not isinstance(line, bytes):
            continue
        m = _LIST_LINE.match(line.strip())
        if not m:
            continue
        name = m.group("name").decode("utf-8", "replace")
        if name.startswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        flags = m.group("flags").decode("ascii", "replace").lower().split()
        if name.upper() == "INBOX" or "\\noselect" in flags:
            continue
        if "\\junk" in flags:
            flagged.append(name)
        elif name.lower() in _SPAM_NAMES:
            named.append(name)
    return flagged or named


def _quoted(mailbox: str) -> str:
    return mailbox if mailbox.isalnum() else '"' + mailbox.replace("\\", "\\\\").replace('"', '\\"') + '"'


def insert_inbound(db: Any, row: dict) -> None:
    db.execute(
        """insert into inbound_email (source_id, received_at, from_addr, subject, r2_key, text_body,
             html_body) values (%(source_id)s, %(received_at)s, %(from_addr)s, %(subject)s,
             %(r2_key)s, %(text_body)s, %(html_body)s)""", row)


def eml_key(received_at: datetime) -> str:
    """R2 key of a raw message: ``inbound/<YYYY-MM-DD>/<uuid>.eml`` (UTC date received)."""
    day = received_at.astimezone(timezone.utc).date().isoformat()
    return f"inbound/{day}/{uuid.uuid4()}.eml"


def collect(ctx: Any, allow: dict[str, list[str]], *,
            connect: Callable[[], imaplib.IMAP4] | None = None,
            insert: Callable[[dict], None] | None = None,
            source_exists: Callable[[str], bool] | None = None,
            mailboxes: Iterable[str] | None = None, held: dict[str, int] | None = None,
            authserv_domains: Iterable[str] | None = None,
            dkim_dns: Callable[..., bytes | None] | None = None) -> dict[str, int]:
    """Pull matching UNSEEN mail. ``allow`` maps source_id → From domains. Returns count per source.
    ``held`` (if given) receives, per source, the messages left unread because the sender could not be
    verified or the message was too big. ``mailboxes``: the folders read, by default the Inbox and the
    spam folder (``junk_folders``); the same rules apply in each, and nothing is moved or deleted.

    ``connect``, ``insert`` and ``source_exists`` are injectable for tests; by default the
    environment and ``ctx.db``; ``dkim_dns`` replaces the DNS lookup of our own DKIM check. A message whose source row is missing is skipped (left unread).
    Raises ``RuntimeError(NOT_CONFIGURED)`` when the IMAP variables are absent.
    """
    if connect is None:
        if not imap_configured():
            raise RuntimeError(NOT_CONFIGURED)
        connect = _connect
    if insert is None:
        if ctx.db is None:
            raise RuntimeError("inbound_email needs the database")
        insert = lambda row: insert_inbound(ctx.db, row)  # noqa: E731
    if source_exists is None and ctx.db is not None:
        source_exists = lambda sid: ctx.db.fetchone(  # noqa: E731
            "select 1 from source where id = %(s)s", {"s": sid}) is not None
    skipped: list[str] = []
    counts = {sid: 0 for sid in allow}
    held = held if held is not None else {}
    authserv = list(authserv_domains) if authserv_domains is not None else trusted_authserv_domains()
    conn = connect()
    try:
        boxes = list(mailboxes) if mailboxes is not None else ["INBOX", *junk_folders(conn)]
        log.info("imap: reading %s", ", ".join(boxes))
        for box in boxes:
            status, _ = conn.select(_quoted(box))
            if status != "OK":
                log.warning("imap: folder %s could not be opened (%s); skipped", box, status)
                continue
            status, data = conn.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                raise RuntimeError(f"IMAP search failed in {box}: {status}")
            for uid in (data[0] or b"").split():
                status, hdr = conn.uid("FETCH", uid,
                                       "(BODY.PEEK[HEADER])")
                if status != "OK" or not hdr or not isinstance(hdr[0], tuple):
                    continue
                _, addr = parseaddr(email.message_from_bytes(hdr[0][1]).get("From", ""))
                domain = addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""
                source_id = next((sid for sid, doms in allow.items() if domain_matches(domain, doms)),
                                 None)
                if source_id is None:
                    continue  # not ours: left unread and untouched
                head = hdr[0][1]
                verified = sender_verified(head, allow[source_id], authserv)
                if not verified and has_trusted_verdict(head, authserv):
                    log.warning("imap: message %s claims %s but the sender is not verified (trusting %s; "
                                "saw %s); left unread", uid, domain, authserv, auth_summary(head))
                    held[source_id] = held.get(source_id, 0) + 1
                    continue
                status, body = conn.uid("FETCH", uid, "(BODY.PEEK[])")
                if status != "OK" or not body or not isinstance(body[0], tuple):
                    continue
                raw = body[0][1]
                if len(raw) > MAX_RAW_BYTES:
                    log.warning("imap: message %s is %d bytes; left unread", uid, len(raw))
                    held[source_id] = held.get(source_id, 0) + 1
                    continue
                if not verified:
                    signer = dkim_verified(raw, allow[source_id], dkim_dns)
                    if signer is None:
                        log.warning("imap: message %s claims %s but the sender is not verified (trusting %s; "
                                    "saw %s; own DKIM check: no valid signature from it); left unread",
                                    uid, domain, authserv, auth_summary(head))
                        held[source_id] = held.get(source_id, 0) + 1
                        continue
                    log.info("imap: message %s from %s: no server verdict; own DKIM check passed (d=%s)",
                             uid, domain, signer)
                if source_exists is not None and not source_exists(source_id):
                    log.warning("imap: no source row %s; message %s left unread", source_id, uid)
                    skipped.append(source_id)
                    continue
                parsed = parse_message(raw)
                key = eml_key(parsed.received_at)
                _, key = ctx.archiver.put_named(key, raw, "message/rfc822")
                insert({"source_id": source_id, "received_at": parsed.received_at,
                        "from_addr": parsed.from_addr, "subject": parsed.subject, "r2_key": key,
                        "text_body": parsed.text_body, "html_body": parsed.html_body})
                conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
                counts[source_id] += 1
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - best effort
            pass
    return counts
