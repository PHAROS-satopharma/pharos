"""PHAROS Telegram alerts: immediate notices, the daily class digest, the daily count of new items on the
authorities' pages, health alerts, admin reports.

Nothing real is sent while ``app_setting.telegram_dry_run`` is true (the default until the owner
approves the first message), while the environment has ``DRY_RUN=1``, when the run was started with
``--dry-run``, or when ``TELEGRAM_BOT_TOKEN`` is absent. A dry run still writes the notification row
(``dry_run = true``) with the exact message text in ``summary``, so the owner can read what would go.

Messages carry public regulatory content only — never reviewer comments. HTML parse mode, every
value escaped. At most one message per second per chat.
"""

from __future__ import annotations

import html
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

CAIRO = ZoneInfo("Africa/Cairo")
API = "https://api.telegram.org"
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
DIGEST_WINDOW = timedelta(hours=4, minutes=30)   # the digest goes out on the first run after the hour
ALERT_RETRY = timedelta(days=2)  # a refused immediate alert is tried again on every run for this long after the first refusal
MAX_DIGEST_ITEMS = 60          # newest first; the rest are named as a count with a pointer to PHAROS
MAX_MESSAGE_CHARS = 4000       # Telegram refuses a message over 4096 characters
BRAND = "PHAROS"
SOURCES_URL = "https://pharos-satopharma.pages.dev/sources"
INGREDIENTS_URL = "https://pharos-satopharma.pages.dev/ingredients"

DOC_TYPE_LABEL = {
    "dhpc": "Direct healthcare professional communication",
    "safety_alert": "Safety alert",
    "safety_update": "Safety update",
    "recall": "Recall",
    "psusa": "PSUSA outcome",
    "label_change": "Product information change",
    "signal": "Safety signal",
    "newsletter": "Safety newsletter",
    "literature": "Literature",
    "other": "Notice",
}


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def esc_cut(value: Any, limit: int) -> str:
    """Escaped and at most ``limit`` characters. The raw text is cut, never the escaped one, so no
    entity is left half (Telegram refuses a whole message over a broken ``&amp;``)."""
    text = "" if value is None else str(value)
    out = esc(text)
    while len(out) > limit:
        text = text[:max(0, len(text) - (len(out) - limit) - 1)]
        out = esc(text) + "…"
    return out


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "date not given"
    if isinstance(d, datetime):
        d = d.astimezone(CAIRO).date()
    return f"{d.day} {d:%b %Y}"


def fmt_cairo_time(t: datetime) -> str:
    t = t.astimezone(CAIRO)
    return f"{t.day} {t:%b %Y}, {t:%H:%M} Cairo time"


class TelegramError(Exception):
    pass


class Telegram:
    """Bot API client. Only constructed when a real send is allowed."""

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self.token = token
        self.client = client or httpx.Client(timeout=60)
        self._last: dict[int, float] = {}

    def _wait(self, chat_id: int) -> None:
        last = self._last.get(chat_id)
        if last is not None:
            gap = 1.0 - (time.monotonic() - last)
            if gap > 0:
                time.sleep(gap)
        self._last[chat_id] = time.monotonic()

    def _call(self, method: str, chat_id: int, **kwargs: Any) -> int:
        self._wait(chat_id)
        for attempt in range(3):
            resp = self.client.post(f"{API}/bot{self.token}/{method}", **kwargs)
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code == 429 and attempt < 2:
                time.sleep(float((data.get("parameters") or {}).get("retry_after", 3)))
                continue
            if not data.get("ok"):
                raise TelegramError(f"{method}: {data.get('description') or resp.status_code}")
            return int(data["result"]["message_id"])
        raise TelegramError(f"{method}: rate limited")

    def send_message(self, chat_id: int, text: str) -> int:
        return self._call("sendMessage", chat_id, data={
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true"})

    def send_document(self, chat_id: int, *, filename: str, content: bytes | None = None,
                      url: str | None = None, caption: str | None = None) -> int:
        data = {"chat_id": chat_id, "parse_mode": "HTML"}
        if caption:
            data["caption"] = caption   # escaped HTML, already cut by the caller (esc_cut)
        if content is not None:
            return self._call("sendDocument", chat_id, data=data,
                              files={"document": (filename, content, "application/pdf")})
        data["document"] = url or ""
        return self._call("sendDocument", chat_id, data=data)


def is_paper(issue: dict) -> bool:
    """An NCBI paper: never an immediate alert, never a class-wide notice in the digest. A paper that looks
    like a case report reaches the daily message in its own block (digest_if_due)."""
    return issue.get("doc_type") == "literature" or issue.get("source_kind") == "literature"


def is_dry_run(settings: dict, flag: bool = False) -> bool:
    return bool(flag or settings.get("telegram_dry_run", True) is not False
                or os.environ.get("DRY_RUN") == "1" or not os.environ.get("TELEGRAM_BOT_TOKEN"))


class Notifier:
    def __init__(self, store: Any, settings: dict, *, dry_run: bool = False, archive: Any = None,
                 telegram: Telegram | None = None, now: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.settings = settings
        self.dry_run = is_dry_run(settings, dry_run)
        self.archive = archive
        self._telegram = telegram
        self.now = now or (lambda: datetime.now(timezone.utc))

    @property
    def telegram(self) -> Telegram:
        if self._telegram is None:
            self._telegram = Telegram(os.environ["TELEGRAM_BOT_TOKEN"])
        return self._telegram

    # ───────────────────────────── message text ─────────────────────────────
    @staticmethod
    def issue_message(issue: dict) -> str:
        ingredients = ", ".join(issue.get("ingredients") or []) or "watched ingredient"
        doc_type = DOC_TYPE_LABEL.get(issue.get("doc_type") or "other", "Notice")
        return "\n".join([
            f"<b>{BRAND}</b> · new notice",
            f"<b>{esc(ingredients)}</b>",
            f"{esc(issue.get('country_name'))} · {esc(issue.get('regulator_name'))}",
            f"{esc(doc_type)} · {esc(fmt_date(issue.get('first_date')))}",
            "",
            esc_cut(issue.get("title_orig") or issue.get("title"), 2000),
            "",
            f'<a href="{html.escape(issue.get("url") or "", quote=True)}">Open the notice</a>',
        ])

    # ───────────────────────────── delivery ─────────────────────────────
    def _deliver(self, person: dict, issue_id: str | None, kind: str, text: str,
                 document: dict | None = None) -> int | None:
        """Send (or record a dry run of) one message; always writes the notification row."""
        message_id, error = None, None
        if not self.dry_run:
            try:
                message_id = self.telegram.send_message(int(person["telegram_chat_id"]), text)
                if document:
                    self.telegram.send_document(int(person["telegram_chat_id"]), **document)
            except (TelegramError, httpx.HTTPError) as exc:
                error = str(exc)[:500]
                log.warning("telegram send failed for %s: %s", person.get("person_id"), error)
        self.store.insert_notification(person_id=person.get("person_id"), issue_id=issue_id,
                                       kind=kind, dry_run=self.dry_run, tg_message_id=message_id,
                                       error=error, summary=text)
        return message_id

    def _pdf_for(self, issue: dict) -> dict | None:
        for att in issue.get("attachments") or []:
            mime = (att.get("mime") or "").lower()
            size = att.get("bytes") or 0
            if mime != "application/pdf" or not size or size > MAX_DOCUMENT_BYTES:
                continue
            name = att.get("filename") or "notice.pdf"
            content = self.archive.get(att["r2_key"]) if (self.archive and att.get("r2_key")) else None
            if content is not None:
                return {"filename": name, "content": content}
            return {"filename": name, "url": att.get("url")}
        return None

    def issue_alert(self, issue_id: str, only: set[str] | None = None) -> int:
        """Immediate message for an ingredient-specific new issue (to ``only`` these people, when
        given). Returns messages written. A paper is never sent: it is read in the app and the report."""
        issue = self.store.issue_for_alert(issue_id)
        if not issue or issue.get("class_only") or issue.get("is_backfill") or is_paper(issue):
            return 0
        people = self.store.subscribers("ingredient", issue.get("ingredient_ids") or [])
        if not people:
            return 0
        text = self.issue_message(issue)
        document = None if self.dry_run else self._pdf_for(issue)
        sent = 0
        for person in people:
            if only is not None and person["person_id"] not in only:
                continue
            if self.store.notified(person["person_id"], issue_id, "immediate"):
                continue
            self._deliver(person, issue_id, "immediate", text, document)
            sent += 1
        return sent

    def retry_refused_alerts(self) -> int:
        """Immediate alerts Telegram refused (or a network error stopped) are sent again, for two days
        from the first refusal, to the people who never got them. Returns messages written."""
        sent = 0
        for issue_id, people in self.store.refused_alerts(self.now() - ALERT_RETRY).items():
            try:
                sent += self.issue_alert(issue_id, only=people)
            except Exception:  # noqa: BLE001 - one retry failing never stops the others
                log.warning("alert retry for %s failed", issue_id, exc_info=True)
        return sent

    def _digest_due_at(self) -> datetime:
        hour = int(self.settings.get("digest_hour_cairo", 9))
        return self.now().astimezone(CAIRO).replace(hour=hour, minute=0, second=0, microsecond=0)

    def digest_due(self) -> bool:
        now = self.now().astimezone(CAIRO)
        due_at = self._digest_due_at()
        if not (due_at <= now < due_at + DIGEST_WINDOW):
            return False
        # Only a digest that really went out counts: a refused one is tried again on the next run,
        # also when it went out to someone else.
        last = self.store.last_notification_at("digest", delivered_only=True, dry_run=self.dry_run)
        return (last is None or last.astimezone(CAIRO) < due_at
                or bool(self.store.refused_people("digest", due_at)))

    @staticmethod
    def digest_parts(header: str, entries: list[tuple[str, str]],
                     more: int) -> list[tuple[str, list[str]]]:
        """Split the digest on entry boundaries, so no message is cut inside a tag or a link. Each part
        keeps the issue ids it carries, so a part that fails is retried without the ones delivered."""
        tail = f"… and {more} more in PHAROS" if more else ""
        parts: list[tuple[str, list[str]]] = []
        current, ids = header + "\n", []   # a blank line under the heading
        for issue_id, entry in entries + ([(None, tail)] if tail else []):
            if len(current) + 1 + len(entry) > MAX_MESSAGE_CHARS:
                parts.append((current, ids))
                current, ids = f"{header} (continued)\n", []
            current += "\n" + entry
            if issue_id is not None:
                ids.append(issue_id)
        parts.append((current, ids))
        return parts

    @staticmethod
    def case_report_entry(paper: dict) -> str:
        """One entry of the "Possible case reports" block: title, journal, day zero (the Cairo day PHAROS
        found it) with the 15-day date for a serious case, and the way to the ingredient's screen."""
        day_zero = paper.get("day_zero")
        due = (f"day zero {fmt_date(day_zero)} · 15 days: {fmt_date(day_zero + timedelta(days=15))}"
               if day_zero else "")
        ing_id = (paper.get("ingredient_ids") or [None])[0]
        link = (f'  <a href="{html.escape(f"{INGREDIENTS_URL}/{ing_id}", quote=True)}">Open the ingredient</a>'
                if ing_id else f"  {INGREDIENTS_URL}")
        meta = " · ".join(x for x in (esc(paper.get("journal")), esc(due)) if x)
        return f"• {esc_cut(paper.get('title_orig'), 2000)}\n" + (f"  {meta}\n" if meta else "") + link

    def digest_if_due(self) -> int:
        """One daily message to class_digest subscribers: the class-only notices, then a block of the papers
        that look like case reports (her decision, 6 Nov 2026: the clock starts the day PHAROS finds the
        paper, so she hears of it that morning). Each notice and each paper goes out once."""
        if not self.digest_due():
            return 0
        # since the last digest of an earlier day: a retry today covers what today's first try did
        last = self.store.last_notification_at("digest", delivered_only=True,
                                               before=self._digest_due_at(), dry_run=self.dry_run)
        since = last or (self.now() - timedelta(days=1))
        all_ids = self.store.class_only_issues_since(since)           # newest first
        papers = self.store.case_report_papers_since(since)           # newest first
        if not all_ids and not papers:
            return 0
        issue_ids = all_ids[:MAX_DIGEST_ITEMS]
        issues = [i for i in (self.store.issue_for_alert(x) for x in issue_ids) if i]
        subject = "class-wide notices" if issues else "possible case reports"
        header = f"<b>{BRAND}</b> · {subject} · {esc(fmt_date(self.now()))}"
        entries = {iss["id"]: f"• {esc(iss.get('country_name'))} · {esc(iss.get('regulator_name'))} · "
                   f"{esc(fmt_date(iss.get('first_date')))}\n  {esc_cut(iss.get('title_orig'), 2000)}\n"
                   f'  <a href="{html.escape(iss.get("url") or "", quote=True)}">Open</a>'
                   for iss in issues}
        entries.update({p["id"]: self.case_report_entry(p) for p in papers})
        sent = 0
        for person in self.store.subscribers("class_digest"):
            # a retry after someone else's refusal: only what this person does not have yet
            # a real digest skips only what really went out: a manual dry run's rows never take a notice
            real = not self.dry_run
            mine = [iss for iss in issues
                    if not self.store.notified(person["person_id"], iss["id"], "digest", real_only=real)]
            my_papers = [p for p in papers
                         if not self.store.notified(person["person_id"], p["id"], "digest", real_only=real)]
            if not mine and not my_papers:
                continue
            listed = [(iss["id"], entries[iss["id"]]) for iss in mine]
            if my_papers:
                listed.append((None, f"<b>Possible case reports ({len(my_papers)})</b>"))
                listed += [(p["id"], entries[p["id"]]) for p in my_papers]
            parts = self.digest_parts(header, listed, len(all_ids) - len(issue_ids))
            # each issue is recorded against the part that carried it: when part 2 is refused, part 1's
            # issues count as delivered and only the rest wait for the retry
            failed = None
            for text, ids in parts:
                message_id, error = None, failed
                if not self.dry_run and failed is None:
                    try:
                        message_id = self.telegram.send_message(int(person["telegram_chat_id"]), text)
                    except (TelegramError, httpx.HTTPError) as exc:
                        error = failed = str(exc)[:500]
                        log.warning("digest send failed for %s: %s", person.get("person_id"), error)
                for issue_id in ids:
                    self.store.insert_notification(person_id=person["person_id"], issue_id=issue_id,
                                                   kind="digest", dry_run=self.dry_run,
                                                   tg_message_id=message_id, error=error, summary=text)
            sent += 1
        return sent

    @staticmethod
    def new_items_message(since: datetime, counts: list[dict]) -> str:
        lines = [f"<b>{BRAND}</b> · new items",
                 f"New on the authorities' pages since {esc(fmt_cairo_time(since))}:", ""]
        lines += [f"{esc(c.get('country_name') or 'Unknown country')}: {int(c['n'])}" for c in counts]
        lines += ["", SOURCES_URL]
        return "\n".join(lines)

    def new_items_digest_if_due(self) -> int:
        """Once a day, on the first run after the digest hour: one message to each new_items_digest
        subscriber with, per country, how many items its authorities published since the last such message
        (new_items() in 0032, the list the Sources screen shows). Nothing is sent when nothing is new. A
        refused message is tried again on the next run inside the window, to the people who did not get it.
        Returns messages written."""
        now = self.now()
        due_at = self._digest_due_at()
        if not (due_at <= now.astimezone(CAIRO) < due_at + DIGEST_WINDOW):
            return 0
        people = [p for p in self.store.subscribers("new_items_digest")
                  if not self.store.notified_since(p["person_id"], "new_items_digest", due_at,
                                                   dry_run=self.dry_run)]
        if not people:
            return 0
        # since the last message of an earlier day: a retry today covers what today's first try did
        last = self.store.last_notification_at("new_items_digest", delivered_only=True, before=due_at,
                                               dry_run=self.dry_run)
        since = last or (now - timedelta(days=1))
        counts = self.store.new_item_counts(since, now)
        if not counts:
            return 0
        text = self.new_items_message(since, counts)
        for person in people:
            self._deliver(person, None, "new_items_digest", text)
        return len(people)

    def health_alert(self, source_id: str, health: str, detail: str) -> int:
        """Source down / degraded / blocked → admins with an admin_health subscription only."""
        labels = {"down": "is down (3 failed runs in a row)", "degraded": "needs attention",
                  "blocked": "is blocked by a bot check", "gap": "may have missed notices"}
        text = (f"<b>{BRAND}</b> · source health\n<b>{esc(source_id)}</b> "
                f"{esc(labels.get(health, health))}\n{esc_cut(detail, 600)}")
        people = self.store.subscribers("admin_health")
        for person in people:
            self._deliver(person, None, "health", text)
        return len(people)

    def admin_message(self, text: str, kind: str = "report") -> int:
        """Split on line ends, like the digest, so a long backfill summary stays under Telegram's limit."""
        messages, current = [], f"<b>{BRAND}</b>"
        for line in text.splitlines():
            line = esc_cut(line, MAX_MESSAGE_CHARS - 100)
            if len(current) + 1 + len(line) > MAX_MESSAGE_CHARS:
                messages.append(current)
                current = f"<b>{BRAND}</b> (continued)"
            current += "\n" + line
        messages.append(current)
        people = self.store.subscribers("admin_health")
        for person in people:
            for message in messages:
                self._deliver(person, None, kind, message)
        return len(people)

    def admin_document(self, filename: str, content: bytes, caption: str) -> int:
        """The monthly report to every admin with Telegram linked (dry-run aware). It is a safety outcome, not
        a health alert: the QPPV is an admin without "Source health alerts" and still receives it."""
        people = self.store.admins()
        doc = {"filename": filename, "content": content, "caption": esc_cut(caption, 1000)}
        for person in people:
            self._deliver(person, None, "report", f"<b>{BRAND}</b>\n{esc(caption)}", doc)
        return len(people)
