"""PHAROS — email one person the steps to connect Telegram, from the PV mailbox.

PHAROS itself sends only the sign-in invitation. Someone who has not connected Telegram receives no
alert at all, so an administrator can send them these steps (workflow "PHAROS Telegram steps email",
run by hand). One person, one message, a fixed text: nothing from the request goes into the body
except the greeting.

The person must be an active PHAROS person whose Telegram is not connected yet; anyone else is
refused before anything is sent. Without ``--send`` the message is only printed.

Sent with SMTP over SSL as ``PHAROS_IMAP_USER`` (pharos@satopharma.com) with the mailbox's app
password ``PHAROS_IMAP_PASSWORD``, the same login the collectors read the mailbox with. The SMTP
server is ``PHAROS_SMTP_HOST`` (default: the IMAP host with ``imap.`` → ``smtp.``, so
imap.mail.yahoo.com → smtp.mail.yahoo.com), port ``PHAROS_SMTP_PORT`` (465).

The workflow runs it with ``--from-event``: the address, the greeting and "send" are read from the event
file, and the log says only whether it was previewed, sent or refused, never who to (the run logs are
public; see ``collectors/dispatch_inputs.py``).

    python -m collectors.telegram_steps_mail --email someone@example.com --greeting "Dr Someone" [--send]
"""

from __future__ import annotations

import argparse
import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from collectors import dispatch_inputs

SITE_URL = "https://pharos-satopharma.pages.dev"
SUBJECT = "PHAROS: connect Telegram to receive safety notices"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_GREETING = re.compile(r"^[\w .'-]{1,60}$")


class Refused(Exception):
    """The message must not be sent; the reason is for the person running the workflow."""


def find_person(db, email: str) -> dict:
    if not _EMAIL.match(email or ""):
        raise Refused("the address is not an email address")
    row = db.fetchone(
        "select id, full_name, email, active, telegram_chat_id from person where lower(email) = lower(%(e)s)",
        {"e": email})
    if row is None:
        raise Refused("that address is not a PHAROS person; invite them on the People page first")
    if not row["active"]:
        raise Refused("that person is not active in PHAROS")
    if row["telegram_chat_id"] is not None:
        raise Refused("that person has already connected Telegram; nothing to send")
    return row


def body_text(greeting: str, site_url: str = SITE_URL) -> str:
    return f"""Dear {greeting},

Please set up PHAROS, our regulatory safety-notice system, so that it can send you alerts on Telegram.

1. Open the invitation email from PHAROS and choose your password.
2. Sign in at {site_url} and open My account (your initials, top right).
3. Under Telegram, press Connect Telegram.
4. Open the link it shows on the phone where you use Telegram, then press Start in the chat with the bot.

The link works once and expires in 24 hours; press Connect Telegram again for a new one.

Once connected, you will receive a notice as soon as a regulator publishes one that names an ingredient
on the watchlist, and one digest of class-wide notices each morning, Cairo time.

If the invitation link no longer works, please tell Omar Gawish.

PHAROS
Sato Pharma, Pharmacovigilance
"""


def build(person: dict, greeting: str | None, sender: str) -> EmailMessage:
    greet = (greeting or person["full_name"]).strip()
    if not _GREETING.match(greet):
        raise Refused("the greeting has characters a greeting does not need")
    msg = EmailMessage()
    msg["From"] = formataddr(("PHAROS", sender))
    msg["To"] = formataddr((person["full_name"], person["email"]))
    msg["Subject"] = SUBJECT
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body_text(greet))
    return msg


def smtp_host() -> str:
    host = os.environ.get("PHAROS_SMTP_HOST")
    if host:
        return host
    imap = os.environ.get("PHAROS_IMAP_HOST") or ""
    if not imap.startswith("imap."):
        raise Refused("PHAROS_SMTP_HOST is not set and the IMAP host does not start with 'imap.'")
    return "smtp." + imap[len("imap."):]


def send(msg: EmailMessage, smtp_factory=smtplib.SMTP_SSL) -> None:
    port = int(os.environ.get("PHAROS_SMTP_PORT") or 465)
    with smtp_factory(smtp_host(), port, timeout=60, context=ssl.create_default_context()) as smtp:
        smtp.login(os.environ["PHAROS_IMAP_USER"], os.environ["PHAROS_IMAP_PASSWORD"])
        smtp.send_message(msg)


def main(argv: list[str] | None = None, *, db=None, smtp_factory=smtplib.SMTP_SSL) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.telegram_steps_mail")
    ap.add_argument("--email", help="the PHAROS person's email address")
    ap.add_argument("--greeting", default="", help='how the email addresses them, e.g. "Dr Sama"')
    ap.add_argument("--send", action="store_true", help="send it (without this it is only printed)")
    ap.add_argument("--from-event", metavar="PATH",
                    help="read email, greeting and send from the workflow's event file; the log names nobody")
    args = ap.parse_args(argv)
    public = bool(args.from_event)
    if public:
        inputs = dispatch_inputs.read(args.from_event)
        email, greeting = inputs.get("email") or "", inputs.get("greeting") or ""
        do_send = dispatch_inputs.ticked(inputs.get("send"))
    else:
        if not args.email:
            ap.error("--email or --from-event is required")
        email, greeting, do_send = args.email, args.greeting, args.send
    sender = os.environ.get("PHAROS_IMAP_USER") or "pharos@satopharma.com"
    try:
        if db is None:
            from collectors.core.db import Db

            db = Db()
        person = find_person(db, email.strip())
        msg = build(person, greeting or None, sender)
        if public:
            print(f"Email ready: {msg['Subject']}, to an active PHAROS person who has not connected Telegram.")
        else:
            print(f"To: {msg['To']}\nFrom: {msg['From']}\nSubject: {msg['Subject']}\n\n{msg.get_content()}")
        if not do_send:
            print("Not sent: preview only (run with send ticked to send it).")
            return 0
        send(msg, smtp_factory)
    except Refused as exc:
        print(f"Not sent: {exc}", file=sys.stderr)
        return 2
    print(f"Sent, Message-ID {msg['Message-ID']}." if public
          else f"Sent to {person['full_name']} <{person['email']}>, Message-ID {msg['Message-ID']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
