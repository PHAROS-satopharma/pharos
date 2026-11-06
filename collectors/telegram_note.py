"""PHAROS — send one person a written message from the PHAROS bot on Telegram.

The bot otherwise sends only what the collectors find. When an administrator has something to tell a
colleague in PHAROS's own chat (how to use a new screen, a step only they can take), the workflow "PHAROS
Telegram message" sends it, run by hand on main only. One person, one message, the text exactly as given:
sent as plain text (HTML-escaped), never parsed as markup.

The person must be an active PHAROS person whose Telegram is connected; anyone else is refused before
anything is sent. Without ``--send`` the message is only printed. Running the workflow with send ticked is
the administrator's word for that one message, so ``app_setting.telegram_dry_run`` does not hold it back
(as the test message on My account). Every send is recorded in ``notification`` (kind ``report``, no
notice), with the text in ``summary``, delivered or refused.

    MESSAGE="…" python -m collectors.telegram_note --email sama.mosaad@satopharma.com [--send]
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import httpx

from collectors.alerts import MAX_MESSAGE_CHARS, Telegram, TelegramError, esc

_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class Refused(Exception):
    """The message must not be sent; the reason is for the person running the workflow."""


def find_person(db, email: str) -> dict:
    if not _EMAIL.match(email or ""):
        raise Refused(f"not an email address: {email!r}")
    row = db.fetchone(
        "select id, full_name, email, active, telegram_chat_id from person where lower(email) = lower(%(e)s)",
        {"e": email})
    if row is None:
        raise Refused(f"{email} is not a PHAROS person")
    if not row["active"]:
        raise Refused(f"{row['full_name']} is not active in PHAROS")
    if row["telegram_chat_id"] is None:
        raise Refused(f"{row['full_name']} has not connected Telegram yet")
    return row


def message_html(text: str) -> str:
    body = (text or "").replace("\r\n", "\n").strip()
    if not body:
        raise Refused("the message is empty")
    out = esc(body)
    if len(out) > MAX_MESSAGE_CHARS:
        raise Refused(f"the message is {len(out)} characters; Telegram takes at most {MAX_MESSAGE_CHARS}")
    return out


def record(db, person: dict, text: str, message_id: int | None, error: str | None) -> None:
    db.execute(
        """insert into notification (person_id, issue_id, kind, dry_run, tg_message_id, error, summary)
           values (%(p)s, null, 'report', false, %(m)s, %(e)s, %(s)s)""",
        {"p": person["id"], "m": message_id, "e": error, "s": text})


def main(argv: list[str] | None = None, *, db=None, telegram=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.telegram_note")
    ap.add_argument("--email", required=True, help="the PHAROS person's email address")
    ap.add_argument("--send", action="store_true", help="send it (without this it is only printed)")
    args = ap.parse_args(argv)
    try:
        text = message_html(os.environ.get("MESSAGE") or "")
        if db is None:
            from collectors.core.db import Db

            db = Db()
        person = find_person(db, args.email.strip())
        print(f"To: {person['full_name']} <{person['email']}> on Telegram\n\n{text}")
        if not args.send:
            print("Not sent: preview only (run with send ticked to send it).")
            return 0
        if telegram is None:
            token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if not token:
                raise Refused("TELEGRAM_BOT_TOKEN is not set")
            telegram = Telegram(token)
    except Refused as exc:
        print(f"Not sent: {exc}", file=sys.stderr)
        return 2
    try:
        message_id = telegram.send_message(int(person["telegram_chat_id"]), text)
    except (TelegramError, httpx.HTTPError) as exc:
        record(db, person, text, None, str(exc)[:500])
        print(f"Not sent: Telegram refused it: {exc}", file=sys.stderr)
        return 1
    record(db, person, text, message_id, None)
    print(f"Sent to {person['full_name']} on Telegram, message {message_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
