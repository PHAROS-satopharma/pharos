"""Read the PHAROS mailbox (pharos@satopharma.com) over IMAP into ``inbound_email``.

The mailbox subscribes to newsletters (Fimea, TGA) whose web pages cannot be read directly. On each
4h run, before the ``email_inbox`` sources, every UNSEEN message whose From domain is on a source's
allow-list (``options.from_domains`` in sources.yaml) is archived as raw ``message/rfc822`` under
``inbound/<YYYY-MM-DD>/<uuid>.eml``, written
to ``inbound_email`` and only then marked Seen. Other mail is never touched (read with BODY.PEEK).
Never sends mail.

Environment: ``PHAROS_IMAP_HOST``, ``PHAROS_IMAP_PORT`` (993, SSL), ``PHAROS_IMAP_USER``,
``PHAROS_IMAP_PASSWORD``. Absent → skipped, and the caller records 'imap not configured'.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

NOT_CONFIGURED = "imap not configured"


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
        text_body=text_part.get_content() if text_part is not None else None,
        html_body=html_part.get_content() if html_part is not None else None,
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
            mailbox: str = "INBOX") -> dict[str, int]:
    """Pull matching UNSEEN mail. ``allow`` maps source_id → From domains. Returns count per source.

    ``connect``, ``insert`` and ``source_exists`` are injectable for tests; by default the
    environment and ``ctx.db``. A message whose source row is missing is skipped (left unread).
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
    conn = connect()
    try:
        conn.select(mailbox)
        status, data = conn.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        for uid in (data[0] or b"").split():
            status, hdr = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
            if status != "OK" or not hdr or not isinstance(hdr[0], tuple):
                continue
            _, addr = parseaddr(email.message_from_bytes(hdr[0][1]).get("From", ""))
            domain = addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""
            source_id = next((sid for sid, doms in allow.items() if domain_matches(domain, doms)),
                             None)
            if source_id is None:
                continue  # not ours: left unread and untouched
            status, body = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK" or not body or not isinstance(body[0], tuple):
                continue
            if source_exists is not None and not source_exists(source_id):
                log.warning("imap: no source row %s; message %s left unread", source_id, uid)
                skipped.append(source_id)
                continue
            raw = body[0][1]
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
