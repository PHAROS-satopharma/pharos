"""PHAROS — the morning reminder of the five-day clock to the Egyptian Drug Authority.

A finding that concerns us must reach the authority within five days of the day PHAROS first showed it
(migration 0041). Once a Cairo day, from 07:00, every reviewer and administrator with Telegram linked gets the
findings that are late or due within two days (today, tomorrow, the day after), most late first, each with the
link to its ingredient's screen. Nothing goes when nothing is due. The collection run calls
``remind_if_due`` after the daily new-items message (collectors/run.py), never on a backfill. A dry run
(``app_setting.telegram_dry_run``, ``--dry-run``, no bot token) writes the notification row with the exact text
and sends nothing, like every other PHAROS message.

    python -m collectors.reminders            # send if due
    python -m collectors.reminders --dry-run  # write what would go, send nothing
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timezone
from typing import Any, Callable

from collectors.alerts import BRAND, CAIRO, MAX_MESSAGE_CHARS, Notifier, esc, esc_cut, fmt_date

log = logging.getLogger("collectors.reminders")

KIND = "escalation"           # the notification kind of a reminder (notif_kind, 0029)
SEND_FROM = time(7, 0)        # Cairo; the first collection run after it is at about 08:17
WITHIN_DAYS = 2               # due today, tomorrow or the day after
MAX_LINES = 40                # findings per message set; the rest are counted with a pointer to PHAROS
SCREEN_URL = "https://pharos-satopharma.pages.dev/ingredients/{id}"
AUTHORITY = "Egyptian Drug Authority"


def _day(d: date) -> str:
    """"Tue 11 Nov"."""
    return f"{d:%a} {d.day} {d:%b}"


def due_text(due: date, days_left: int) -> str:
    """"due Tue 11 Nov, 1 day left", "due today, Fri 6 Nov" or "3 days late (was due Tue 3 Nov)"."""
    if days_left < 0:
        late = -days_left
        return f"{late} {'day' if late == 1 else 'days'} late (was due {_day(due)})"
    if days_left == 0:
        return f"due today, {_day(due)}"
    return f"due {_day(due)}, {days_left} {'day' if days_left == 1 else 'days'} left"


def build_messages(items: list[dict], today: date) -> list[str]:
    """The reminder text for the findings (as the store lists them: most late first), split under
    Telegram's limit."""
    late = sum(1 for i in items if int(i["days_left"]) < 0)
    due = len(items) - late
    n = len(items)
    lines = [f"<b>{BRAND}</b> · {AUTHORITY} · {esc(fmt_date(today))}",
             f"<b>{n} {'finding' if n == 1 else 'findings'} to report to the authority</b>",
             f"{late} late, {due} due within {WITHIN_DAYS} days", ""]
    for it in items[:MAX_LINES]:
        where = " · ".join(esc(x) for x in (it.get("ingredient"), it.get("country")) if x)
        lines.append(f"• {esc_cut(it.get('title'), 160)}{' · ' + where if where else ''}"
                     f" · {esc(due_text(it['due'], int(it['days_left'])))}")
        lines.append("  " + (SCREEN_URL.format(id=it["ingredient_id"]) if it.get("ingredient_id")
                             else SCREEN_URL.format(id="").rstrip("/")))
    if n > MAX_LINES:
        lines.append(f"… and {n - MAX_LINES} more in PHAROS (Ingredients).")
    messages, current = [], ""
    for line in lines:
        if current and len(current) + 1 + len(line) > MAX_MESSAGE_CHARS:
            messages.append(current)
            current = f"<b>{BRAND}</b> (continued)"
        current = f"{current}\n{line}" if current else line
    messages.append(current)
    return messages


def remind_if_due(store: Any, notifier: Notifier | None = None, *, dry_run: bool = False,
                  now: Callable[[], datetime] | None = None) -> int:
    """Send today's reminder if it is due and something is late or due soon; return how many people it went
    to (0 when it is too early, already went today, nothing is due, or nobody is linked)."""
    moment = (now or (lambda: datetime.now(timezone.utc)))().astimezone(CAIRO)
    if moment.time() < SEND_FROM:
        log.info("the authority reminder waits for %s Cairo", SEND_FROM.strftime("%H:%M"))
        return 0
    midnight = datetime.combine(moment.date(), time(0), CAIRO)
    last = store.last_notification_at(KIND)
    if last is not None and last >= midnight:
        log.info("today's authority reminder has gone already")
        return 0
    items = store.eda_reminders(moment.date(), WITHIN_DAYS)
    if not items:
        log.info("nothing is due to the authority on %s", moment.date())
        return 0
    people = store.reminder_people()
    if not people:
        log.info("nobody with Telegram to remind")
        return 0
    notifier = notifier or Notifier(store, store.settings(), dry_run=dry_run)
    texts = build_messages(items, moment.date())
    for person in people:
        for text in texts:
            notifier._deliver(person, None, KIND, text)
    log.info("authority reminder: %d findings to %d people (dry run: %s)", len(items), len(people),
             notifier.dry_run)
    return len(people)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.reminders", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO")
    from collectors.core.context import install_log_redaction

    install_log_redaction()     # httpx logs api.telegram.org/bot<TOKEN>/… at INFO
    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    try:
        remind_if_due(Store(db), dry_run=args.dry_run)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
