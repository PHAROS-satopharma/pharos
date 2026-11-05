"""PHAROS — the morning escalation: what is late goes to every administrator on Telegram.

Once a Cairo day, from 07:00, the late signals and the notices left unreviewed (``overdue_items``, 0029) go
to every active administrator with Telegram linked, as one message (split when long). Nothing is sent when
nothing is late. A dry run (``app_setting.telegram_dry_run``, ``--dry-run``, no bot token) writes the
notification row with the exact text and sends nothing, like every other PHAROS message.

    python -m collectors.escalate            # send if due
    python -m collectors.escalate --dry-run  # write what would go, send nothing
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, time, timezone
from typing import Any, Callable

from collectors.alerts import BRAND, CAIRO, MAX_MESSAGE_CHARS, Notifier, esc, esc_cut, fmt_date

log = logging.getLogger("collectors.escalate")

SEND_FROM = time(7, 0)    # Cairo; the 12-hour collection runs at about 07:47 / 08:47 and 19:47 / 20:47
MAX_LINES = 40            # per kind; the rest are counted with a pointer to PHAROS


def build_messages(items: list[dict], today: date) -> list[str]:
    """The escalation text for the late items (signals first, then notices), split under Telegram's limit."""
    signals = [i for i in items if i["kind"] == "signal"]
    reviews = [i for i in items if i["kind"] == "review"]
    lines = [f"<b>{BRAND}</b> · late on {esc(fmt_date(today))}"]
    if signals:
        lines += ["", f"<b>{len(signals)} {'signal' if len(signals) == 1 else 'signals'} past due</b>"]
        for s in signals[:MAX_LINES]:
            lines.append(f"• {esc(s['label'])} · {esc_cut(s['title'], 160)}"
                         f"{' · ' + esc(s['ingredient']) if s.get('ingredient') else ''}"
                         f" · due {esc(fmt_date(s['due']))}, {_late(s['days_late'])}")
        if len(signals) > MAX_LINES:
            lines.append(f"… and {len(signals) - MAX_LINES} more in PHAROS (Signals).")
    if reviews:
        lines += ["", f"<b>{len(reviews)} {'notice' if len(reviews) == 1 else 'notices'} not reviewed in time</b>"]
        for r in reviews[:MAX_LINES]:
            lines.append(f"• {esc_cut(r['title'], 160)}"
                         f"{' · ' + esc(r['ingredient']) if r.get('ingredient') else ''}"
                         f" · {_late(r['days_late'])}")
        if len(reviews) > MAX_LINES:
            lines.append(f"… and {len(reviews) - MAX_LINES} more in PHAROS (Notices, status New).")
    messages, current = [], ""
    for line in lines:
        if current and len(current) + 1 + len(line) > MAX_MESSAGE_CHARS:
            messages.append(current)
            current = f"<b>{BRAND}</b> (continued)"
        current = f"{current}\n{line}" if current else line
    messages.append(current)
    return messages


def _late(days: int) -> str:
    return "1 day late" if days == 1 else f"{days} days late"


def escalate(db: Any, store: Any, *, dry_run: bool = False,
             now: Callable[[], datetime] | None = None, notifier: Notifier | None = None) -> int:
    """Send today's escalation if it is due and something is late; return how many people it went to."""
    moment = (now or (lambda: datetime.now(timezone.utc)))().astimezone(CAIRO)
    if moment.time() < SEND_FROM:
        log.info("escalation waits for %s Cairo", SEND_FROM.strftime("%H:%M"))
        return 0
    midnight = datetime.combine(moment.date(), time(0), CAIRO)
    if db.fetchone("select 1 from notification where kind = 'escalation' and sent_at >= %(m)s limit 1",
                   {"m": midnight}):
        log.info("today's escalation has gone already")
        return 0
    items = db.fetchall(
        "select kind, label, title, ingredient, due, days_late from overdue_items(%(d)s) "
        "where kind in ('signal', 'review') order by kind, days_late desc, due",
        {"d": moment.date()})
    if not items:
        log.info("nothing is late on %s", moment.date())
        return 0
    notifier = notifier or Notifier(store, store.settings(), dry_run=dry_run)
    people = store.admins()
    for person in people:
        for text in build_messages(items, moment.date()):
            notifier._deliver(person, None, "escalation", text)
    log.info("escalation: %d late items to %d administrators (dry run: %s)", len(items), len(people),
             notifier.dry_run)
    return len(people)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.escalate", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO")
    from collectors.core.context import install_log_redaction

    install_log_redaction()     # httpx logs api.telegram.org/bot<TOKEN>/… at INFO
    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    try:
        escalate(db, Store(db), dry_run=args.dry_run)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
