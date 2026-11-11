"""PHAROS — the morning reminder of the five-day clock to the Egyptian Drug Authority.

A finding that concerns us must reach the authority within five days of the day PHAROS first showed it
(migrations 0041 and 0050: the day the notice was created). Once a Cairo day, from 07:00, every reviewer and
administrator with Telegram linked gets the findings that are late or due within two days (today, tomorrow, the
day after), most late first, each with the link to its ingredient's screen. Nothing goes when nothing is due.
The collection run calls ``remind_if_due`` after the daily new-items message (collectors/run.py), never on a
backfill. A dry run (``app_setting.telegram_dry_run``, ``--dry-run``, no bot token) writes the notification row
with the exact text and sends nothing, like every other PHAROS message.

Once a day means once to each person it really reached: a dry run never stands in for the real reminder, and a
message Telegram refused is tried again at the next run while the people who got it are not told twice. A long
reminder goes in parts: a refused part is tried again with the parts after it, and the parts the person already
has are not sent again.

After the findings, the same message lists the signal steps that are late or due within two days (migration
0042: the signal Concerns us opened on the finding, waiting to be validated, assessed or acted on), each with
its reference, the notice, the ingredient and the link to the screen where the step is taken. A message goes
when either list has something in it.

Then the quality records (migration 0107), in the same message, never a second one: "CAPA due" (every CAPA not
done or effective whose due day is within two days or past, and every done CAPA whose effectiveness check, set by
PHAROS three months after it was done (0110), is, oldest first: its number, where it comes from, the owner, "due
Thu 19 Nov", "late by 3 days" or "effectiveness check due Thu 19 Nov") and "Audit deadlines" (for each audit with a report received and
not closed, the next deadline of PV-SOP-022 when it is within two days or late), each line with the link to the
Quality tab. A message goes when any of the four lists has something in it. A quality read that fails (before
0107 is applied) is logged and the rest of the reminder goes as before.

Before anything else, from 07:00, the run asks the database to propose as a deviation every deadline it keeps
that passed unmet (migration 0108, deviation_proposals_find: once each, whoever is linked and whatever else is
due), and the message ends with "Proposed deviations": how many wait for a reviewer to record or dismiss, with
the link to the Quality tab. Proposals waiting are enough for the message to go. PHAROS never records a
deviation itself. A finder that fails is logged and the reminder goes as before.

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
from collectors.quality import KIND_LABEL, QUALITY_URL, capa_source_text

log = logging.getLogger("collectors.reminders")

KIND = "escalation"           # the notification kind of a reminder (notif_kind, 0029)
SEND_FROM = time(7, 0)        # Cairo; the first collection run after it is at about 08:17
WITHIN_DAYS = 2               # due today, tomorrow or the day after
MAX_LINES = 40                # findings per message set; the rest are counted with a pointer to PHAROS
SCREEN_URL = "https://pharos-satopharma.pages.dev/ingredients/{id}"
AUTHORITY = "Egyptian Drug Authority"
SIGNALS = "Signal steps"       # the header when no finding is due but a signal step is
QUALITY = "Quality"            # the header when only quality records are due
STAGE_WORD = {"validation": "Validate", "assessment": "Assess", "action": "Action"}   # the step each stage waits for


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


def step_text(stage: str, due: date, days_left: int) -> str:
    """"Validate · due Sat 7 Nov, 1 day left", "Assess · 3 days late (was due Tue 3 Nov)"."""
    return f"{STAGE_WORD.get(stage, stage)} · {due_text(due, days_left)}"


def capa_due_text(due: date, days_left: int) -> str:
    """A CAPA's or an audit deadline's due words: "due Thu 19 Nov" or "late by 3 days"."""
    if days_left < 0:
        late = -days_left
        return f"late by {late} {'day' if late == 1 else 'days'}"
    return f"due {_day(due)}"


def _quality_lines(capas: list[dict] | tuple, audits: list[dict] | tuple, proposals: int = 0) -> list[str]:
    """The "CAPA due" and "Audit deadlines" blocks, each line with the link to the Quality tab, then how many
    proposed deviations wait (0108)."""
    lines: list[str] = []
    for title, rows, more in (("CAPA due", capas, "CAPAs"), ("Audit deadlines", audits, "audit deadlines")):
        if not rows:
            continue
        late = sum(1 for r in rows if int(r["days_left"]) < 0)
        lines += ["", f"<b>{title}</b>", f"{late} late, {len(rows) - late} due within {WITHIN_DAYS} days", ""]
        for r in list(rows)[:MAX_LINES]:
            if title == "CAPA due":
                owner = r.get("owner") or "no owner yet"
                due = capa_due_text(r["due_on"], int(r["days_left"]))
                if r.get("check"):
                    due = f"effectiveness check {due}"
                text = f"• {esc(r.get('ref'))} · {esc_cut(capa_source_text(r), 160)} · {esc(owner)} · {esc(due)}"
            else:
                kind = KIND_LABEL.get(r.get("kind") or "", "Audit")
                text = (f"• {esc_cut(r.get('title'), 160)} · {esc(kind)} · {esc(r.get('step'))}"
                        f" · {esc(capa_due_text(r['due'], int(r['days_left'])))}")
            lines += [text, "  " + QUALITY_URL]
        if len(rows) > MAX_LINES:
            lines.append(f"… and {len(rows) - MAX_LINES} more {more} in PHAROS (Quality).")
    if proposals:
        lines += ["", "<b>Proposed deviations</b>",
                  f"{proposals} missed {'deadline waits' if proposals == 1 else 'deadlines wait'}: "
                  "record as a deviation or dismiss with the reason", "  " + QUALITY_URL]
    return lines


def _screen_link(ingredient_id: str | None) -> str:
    return "  " + (SCREEN_URL.format(id=ingredient_id) if ingredient_id else SCREEN_URL.format(id="").rstrip("/"))


def build_messages(items: list[dict], today: date, signals: list[dict] | tuple = (), *,
                   capas: list[dict] | tuple = (), audits: list[dict] | tuple = (), proposals: int = 0) -> list[str]:
    """The reminder text: the findings to report to the authority (as the store lists them: most late first),
    then the signal steps due (0042), then the CAPAs due and the audit deadlines (0107), split under Telegram's
    limit."""
    late = sum(1 for i in items if int(i["days_left"]) < 0)
    due = len(items) - late
    n = len(items)
    header = AUTHORITY if items else SIGNALS if signals or not (capas or audits or proposals) else QUALITY
    lines = [f"<b>{BRAND}</b> · {header} · {esc(fmt_date(today))}"]
    if items:
        lines += [f"<b>{n} {'finding' if n == 1 else 'findings'} to report to the authority</b>",
                  f"{late} late, {due} due within {WITHIN_DAYS} days", ""]
    for it in items[:MAX_LINES]:
        where = " · ".join(esc(x) for x in (it.get("ingredient"), it.get("country")) if x)
        lines.append(f"• {esc_cut(it.get('title'), 160)}{' · ' + where if where else ''}"
                     f" · {esc(due_text(it['due'], int(it['days_left'])))}")
        lines.append(_screen_link(it.get("ingredient_id")))
    if n > MAX_LINES:
        lines.append(f"… and {n - MAX_LINES} more in PHAROS (Ingredients).")
    if signals:
        s_late = sum(1 for s in signals if int(s["days_left"]) < 0)
        m = len(signals)
        lines += ["" if items else "",
                  f"<b>{m} signal {'step' if m == 1 else 'steps'} due</b>",
                  f"{s_late} late, {m - s_late} due within {WITHIN_DAYS} days", ""]
        for s in list(signals)[:MAX_LINES]:
            where = esc(s["ingredient"]) if s.get("ingredient") else ""
            lines.append(f"• {esc(s.get('ref'))} · {esc_cut(s.get('title'), 160)}{' · ' + where if where else ''}"
                         f" · {esc(step_text(s['stage'], s['next_due'], int(s['days_left'])))}")
            lines.append(_screen_link(s.get("ingredient_id")))
        if m > MAX_LINES:
            lines.append(f"… and {m - MAX_LINES} more signal steps in PHAROS (Ingredients).")
    lines += _quality_lines(capas, audits, proposals)
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
    proposals = _proposals(store, moment.date())
    notifier = notifier or Notifier(store, store.settings(), dry_run=dry_run)
    if now is not None:
        notifier.now = now      # the rows it writes carry the same clock the day window is cut from
    # Once a day, per person: whoever the reminder really reached today is not told again. Only a delivered
    # message counts (a refused one is tried again now); a dry run stands in only for another dry run.
    told = store.told_since(KIND, midnight, dry_run=notifier.dry_run)
    people = [p for p in store.reminder_people() if p["person_id"] not in told]
    if not people:
        log.info("today's authority reminder has gone already" if told else "nobody with Telegram to remind")
        return 0
    items = store.eda_reminders(moment.date(), WITHIN_DAYS)
    signals = store.signal_reminders(moment.date(), WITHIN_DAYS)
    capas, audits = _quality_due(store, moment.date())
    if not items and not signals and not capas and not audits and not proposals:
        log.info("nothing is due to the authority, and no signal step, CAPA, audit deadline or proposed "
                 "deviation waits, on %s", moment.date())
        return 0
    texts = build_messages(items, moment.date(), signals, capas=capas, audits=audits, proposals=proposals)
    for person in people:
        # a retry sends only the parts this person does not have; a refused part holds back the ones after it
        # (written down as refused), so they always arrive in order
        have = store.delivered_texts(person["person_id"], KIND, midnight, dry_run=notifier.dry_run)
        failed = None
        for text in texts:
            if text in have:
                continue
            if failed:
                store.insert_notification(person_id=person["person_id"], issue_id=None, kind=KIND,
                                          dry_run=notifier.dry_run, tg_message_id=None, error=failed, summary=text,
                                          sent_at=notifier.now())
                continue
            if notifier._deliver(person, None, KIND, text) is None and not notifier.dry_run:
                failed = "held back: an earlier part was refused"
    log.info("morning reminder: %d findings, %d signal steps, %d CAPAs and %d audit deadlines to %d people "
             "(dry run: %s)", len(items), len(signals), len(capas), len(audits), len(people), notifier.dry_run)
    return len(people)


def _proposals(store: Any, today: date) -> int:
    """Runs the finder of proposed deviations (0108) and returns how many wait. A failure (the migration not
    applied yet) is logged and counts none: the rest of the reminder still goes."""
    try:
        new = store.find_deviation_proposals(today)
        if new:
            log.info("%d missed deadlines proposed as deviations on %s", new, today)
        return store.deviation_proposals_waiting()
    except Exception as e:  # noqa: BLE001 - never let the proposals stop the authority reminder
        log.warning("the proposed deviations could not be found for the morning reminder: %s", e)
        return 0


def _quality_due(store: Any, today: date) -> tuple[list[dict], list[dict]]:
    """The CAPAs due and the audit deadlines (0107). A read that fails (the migration not applied yet) is logged
    and leaves both empty: the findings and the signal steps still go."""
    try:
        return store.capa_reminders(today, WITHIN_DAYS), store.audit_deadline_reminders(today, WITHIN_DAYS)
    except Exception as e:  # noqa: BLE001 - never let the quality records stop the authority reminder
        log.warning("the quality records could not be read for the morning reminder: %s", e)
        return [], []


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
