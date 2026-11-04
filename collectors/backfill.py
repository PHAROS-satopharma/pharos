"""Backfill helpers (``python -m collectors.run --backfill``).

Reads ``app_setting.backfill_months`` (12) of history from every enabled source; EMA structured
sources (``options.backfill_all: true``) keep their whole history. Every document and issue is
flagged ``is_backfill``, no alert is sent, and the admins get one summary at the end (dry-run aware).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from collectors.core.models import Item, SourceConfig


def cutoff(settings: dict, today: date | None = None) -> date:
    months = int(settings.get("backfill_months", 12) or 12)
    today = today or date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)
    return date(year, month, day)


def in_window(item: Item, source: SourceConfig, start: date) -> bool:
    if source.options.get("backfill_all"):
        return True
    return item.published is None or item.published >= start


@dataclass
class BackfillSummary:
    start: date
    per_source: dict[str, dict] = field(default_factory=dict)

    def add(self, source_id: str, *, seen: int, new: int, matched: int, error: str | None) -> None:
        self.per_source[source_id] = {"seen": seen, "new": new, "matched": matched, "error": error}

    def text(self, issues_created: int) -> str:
        ok = [s for s, v in self.per_source.items() if not v["error"]]
        failed = {s: v["error"] for s, v in self.per_source.items() if v["error"]}
        new = sum(v["new"] for v in self.per_source.values())
        matched = sum(v["matched"] for v in self.per_source.values())
        lines = [f"Backfill from {self.start:%d %b %Y} finished.",
                 f"Sources read: {len(ok)} of {len(self.per_source)}.",
                 f"Documents stored: {new}; matched: {matched}; issues created: {issues_created}.",
                 "No alerts were sent for backfilled items."]
        if failed:
            lines.append("Sources that failed:")
            lines += [f"- {s}: {e[:120]}" for s, e in sorted(failed.items())]
        return "\n".join(lines)

