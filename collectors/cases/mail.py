"""Cases forwarded to the PHAROS mailbox: a reviewer or an administrator forwards the report to
pharos@satopharma.com with the word CASE in the subject, and the case opens by itself.

Each UNSEEN message whose subject has the word CASE and whose From address is an active reviewer's or
administrator's own email (``person.email``) is checked like newsletter mail (``collectors/core/imap_inbox.py``):
the receiving server's verdict must pass for the sender's domain, or, when the server gave none, PHAROS's own DKIM
check must. Then the raw message is archived under ``inbound/`` (never overwritten), written to ``inbound_email``
(no source: it is not a newsletter), and the case is opened (origin email, day zero the Cairo day the message is
dated, the forwarding person as its creator), all in one transaction; only then is the message marked Seen.
Any other message is left unread and untouched. Never sends mail.
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from collectors.core.archive import Archive, sha256_hex
from collectors.core.imap_inbox import (MAX_RAW_BYTES, NOT_CONFIGURED, _connect, auth_summary, dkim_verified,
                                        eml_key, has_trusted_verdict, imap_configured, parse_message,
                                        sender_verified, trusted_authserv_domains)

log = logging.getLogger("collectors.cases.mail")

CAIRO = ZoneInfo("Africa/Cairo")
SUBJECT_WORD = re.compile(r"(?<![A-Za-z])case(?![A-Za-z])", re.I)


def team(db: Any) -> dict[str, str]:
    """Active reviewers and administrators: lower-case email → person id."""
    rows = db.fetchall("""select id, lower(email) as email from person
                           where active and role in ('admin','reviewer') and email is not null""")
    return {r["email"]: str(r["id"]) for r in rows}


def cairo_day(when: datetime) -> str:
    return when.astimezone(CAIRO).date().isoformat()


def open_case(db: Any, archive: Archive, raw: bytes, person_id: str) -> str:
    """Archive the message and open its case; the case's id."""
    parsed = parse_message(raw)
    _, key = archive.put_named(eml_key(parsed.received_at), raw, "message/rfc822")
    subject = (parsed.subject or "Forwarded report").strip()[:200]
    today = datetime.now(CAIRO).date().isoformat()
    day_zero = min(cairo_day(parsed.received_at), today)   # a message dated in the future counts from today
    with db.transaction():
        inbound = db.fetchone(
            """insert into inbound_email (source_id, received_at, from_addr, subject, r2_key, text_body, html_body,
                                          processed_at)
               values (null, %(at)s, %(f)s, %(s)s, %(k)s, %(t)s, %(h)s, now()) returning id""",
            {"at": parsed.received_at, "f": parsed.from_addr, "s": parsed.subject, "k": key,
             "t": parsed.text_body, "h": parsed.html_body})
        case = db.fetchone(
            """insert into safety_case (ref, origin, status, inbound_email_id, file_name, mime, sha256, r2_key, bytes,
                                        day_zero, created_by)
               values (case_new_ref(), 'email', 'queued', %(e)s, %(n)s, 'message/rfc822', %(sha)s, %(k)s, %(b)s,
                       %(d)s, %(p)s)
               returning id, ref""",
            {"e": inbound["id"], "n": subject, "sha": sha256_hex(raw), "k": key, "b": len(raw), "d": day_zero,
             "p": person_id})
        db.execute("""insert into case_event (case_id, step, from_status, to_status, comment, person_id)
                      values (%(c)s, 'received', null, 'queued', %(m)s, %(p)s)""",
                   {"c": case["id"], "m": f"Forwarded to the PHAROS mailbox: {subject}", "p": person_id})
    log.info("mail: opened %s from a forwarded message", case["ref"])
    return str(case["id"])


def collect(db: Any, archive: Archive, *, connect: Callable[[], imaplib.IMAP4] | None = None,
            authserv_domains: Iterable[str] | None = None,
            dkim_dns: Callable[..., bytes | None] | None = None, mailbox: str = "INBOX") -> dict[str, int]:
    """Open a case for every forwarded report waiting in the mailbox. Counts: opened, held (sender not verified
    or message too big). Raises ``RuntimeError(NOT_CONFIGURED)`` without the IMAP variables."""
    if connect is None:
        if not imap_configured():
            raise RuntimeError(NOT_CONFIGURED)
        connect = _connect
    people = team(db)
    authserv = list(authserv_domains) if authserv_domains is not None else trusted_authserv_domains()
    counts = {"opened": 0, "held": 0}
    if not people:
        return counts
    conn = connect()
    try:
        conn.select(mailbox)
        status, data = conn.uid("SEARCH", None, "UNSEEN")
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")
        for uid in (data[0] or b"").split():
            status, hdr = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER])")
            if status != "OK" or not hdr or not isinstance(hdr[0], tuple):
                continue
            head = hdr[0][1]
            msg = email.message_from_bytes(head)
            _, addr = parseaddr(str(msg.get("From", "")))
            person = people.get(addr.strip().lower())
            if person is None or not SUBJECT_WORD.search(str(msg.get("Subject", ""))):
                continue  # not a forwarded case: left unread and untouched
            domain = addr.rsplit("@", 1)[-1].lower()
            verified = sender_verified(head, [domain], authserv)
            if not verified and has_trusted_verdict(head, authserv):
                log.warning("mail: message %s claims a team address but the sender is not verified (%s); left "
                            "unread", uid, auth_summary(head))
                counts["held"] += 1
                continue
            status, body = conn.uid("FETCH", uid, "(BODY.PEEK[])")
            if status != "OK" or not body or not isinstance(body[0], tuple):
                continue
            raw = body[0][1]
            if len(raw) > MAX_RAW_BYTES:
                log.warning("mail: message %s is %d bytes; left unread", uid, len(raw))
                counts["held"] += 1
                continue
            if not verified and dkim_verified(raw, [domain], dkim_dns) is None:
                log.warning("mail: message %s claims a team address with no server verdict and no valid DKIM "
                            "signature (%s); left unread", uid, auth_summary(head))
                counts["held"] += 1
                continue
            if db.fetchone("select 1 from safety_case where origin = 'email' and sha256 = %(s)s",
                           {"s": sha256_hex(raw)}) is None:
                open_case(db, archive, raw, person)   # else: opened by a run that could not mark it Seen
            conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
            counts["opened"] += 1
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 - best effort
            pass
    return counts
