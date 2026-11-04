"""PHAROS Telegram alerts: immediate notices, the daily class digest, health alerts, admin reports.

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
MAX_DIGEST_ITEMS = 30
BRAND = "PHAROS"

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


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "date not given"
    if isinstance(d, datetime):
        d = d.astimezone(CAIRO).date()
    return f"{d.day} {d:%b %Y}"


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
            data["caption"] = caption[:1000]
        if content is not None:
            return self._call("sendDocument", chat_id, data=data,
                              files={"document": (filename, content, "application/pdf")})
        data["document"] = url or ""
        return self._call("sendDocument", chat_id, data=data)


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
            esc(issue.get("title_orig") or issue.get("title")),
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

    def issue_alert(self, issue_id: str) -> int:
        """Immediate message for an ingredient-specific new issue. Returns messages written."""
        issue = self.store.issue_for_alert(issue_id)
        if not issue or issue.get("class_only") or issue.get("is_backfill"):
            return 0
        people = self.store.subscribers("ingredient", issue.get("ingredient_ids") or [])
        if not people:
            return 0
        text = self.issue_message(issue)
        document = None if self.dry_run else self._pdf_for(issue)
        sent = 0
        for person in people:
            if self.store.notified(person["person_id"], issue_id, "immediate"):
                continue
            self._deliver(person, issue_id, "immediate", text, document)
            sent += 1
        return sent

    def digest_due(self) -> bool:
        now = self.now().astimezone(CAIRO)
        hour = int(self.settings.get("digest_hour_cairo", 9))
        due_at = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if not (due_at <= now < due_at + DIGEST_WINDOW):
            return False
        last = self.store.last_notification_at("digest")
        return last is None or last.astimezone(CAIRO) < due_at

    def digest_if_due(self) -> int:
        """One daily digest of class-only issues to class_digest subscribers."""
        if not self.digest_due():
            return 0
        last = self.store.last_notification_at("digest")
        since = last or (self.now() - timedelta(days=1))
        issue_ids = self.store.class_only_issues_since(since)[:MAX_DIGEST_ITEMS]
        if not issue_ids:
            return 0
        issues = [i for i in (self.store.issue_for_alert(x) for x in issue_ids) if i]
        lines = [f"<b>{BRAND}</b> · class-wide notices · {esc(fmt_date(self.now()))}", ""]
        for iss in issues:
            lines.append(f"• {esc(iss.get('country_name'))} · {esc(iss.get('regulator_name'))} · "
                         f"{esc(fmt_date(iss.get('first_date')))}\n  {esc(iss.get('title_orig'))}\n"
                         f'  <a href="{html.escape(iss.get("url") or "", quote=True)}">Open</a>')
        text = "\n".join(lines)[:4000]
        sent = 0
        for person in self.store.subscribers("class_digest"):
            message_id, error = None, None
            if not self.dry_run:
                try:
                    message_id = self.telegram.send_message(int(person["telegram_chat_id"]), text)
                except (TelegramError, httpx.HTTPError) as exc:
                    error = str(exc)[:500]
            for iss in issues:
                self.store.insert_notification(person_id=person["person_id"], issue_id=iss["id"],
                                               kind="digest", dry_run=self.dry_run,
                                               tg_message_id=message_id, error=error, summary=text)
            sent += 1
        return sent

    def health_alert(self, source_id: str, health: str, detail: str) -> int:
        """Source down / degraded / blocked → admins with an admin_health subscription only."""
        labels = {"down": "is down (3 failed runs in a row)", "degraded": "needs attention",
                  "blocked": "is blocked by a bot check"}
        text = (f"<b>{BRAND}</b> · source health\n<b>{esc(source_id)}</b> "
                f"{esc(labels.get(health, health))}\n{esc(detail)[:600]}")
        people = self.store.subscribers("admin_health")
        for person in people:
            self._deliver(person, None, "health", text)
        return len(people)

    def admin_message(self, text: str, kind: str = "report") -> int:
        people = self.store.subscribers("admin_health")
        for person in people:
            self._deliver(person, None, kind, f"<b>{BRAND}</b>\n{esc(text)}")
        return len(people)

    def admin_document(self, filename: str, content: bytes, caption: str) -> int:
        """The monthly report to the admins (dry-run aware)."""
        people = self.store.subscribers("admin_health")
        doc = {"filename": filename, "content": content, "caption": esc(caption)}
        for person in people:
            self._deliver(person, None, "report", f"<b>{BRAND}</b>\n{esc(caption)}", doc)
        return len(people)
