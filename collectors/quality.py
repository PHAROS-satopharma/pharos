"""PHAROS — the quality records of migration 0107 (deviations, audits, the CAPA plan) in her words, for the morning
reminder (collectors/reminders.py) and the inspection pack (collectors/report_pack.py).

The words are the Quality tab's own (web/src/features/quality/quality.ts). The audit deadlines are those of
PV-SOP-022, counted from the day the report was received, as quality_audit_deadlines() counts them in 0107:
QPPV review +1 day, meeting +2, draft CAPA +10, approval +12, submission +14. The day each was done is kept on
the audit row.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

QUALITY_URL = "https://pharos-satopharma.pages.dev/quality"

# (key, her words, days after the report, the audit column the day it was done is kept in)
AUDIT_STEPS: tuple[tuple[str, str, int, str], ...] = (
    ("review", "QPPV review of the report", 1, "reviewed_on"),
    ("meeting", "Meeting with the responsible persons", 2, "meeting_on"),
    ("draft", "Draft CAPA", 10, "capa_drafted_on"),
    ("approval", "All CAPAs reviewed and approved", 12, "capa_approved_on"),
    ("submission", "CAPA submitted", 14, "capa_submitted_on"),
)

KIND_LABEL = {"internal": "Internal audit", "external": "External audit"}
GRADE_LABEL = {"critical": "Critical", "major": "Major", "minor": "Minor"}
DEVIATION_STATUS_LABEL = {"open": "Recorded", "investigating": "Under investigation", "capa": "CAPA planned",
                          "approved": "Approved by the QA Manager", "closed": "Closed"}
AUDIT_STATUS_LABEL = {"planned": "Planned", "report_received": "Report received",
                      "capa_submitted": "CAPA submitted", "closed": "Closed"}
CAPA_STATUS_LABEL = {"draft": "Draft", "approved": "Approved", "in_progress": "In progress",
                     "done": "Done, to verify", "effective": "Effective (closed)"}
CAPA_FINISHED = ("done", "effective")      # off the reminder: done waits only for the check that it worked


def audit_deadlines(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """The five deadlines of an audit whose report was received, in order: key, label, due, done_on.
    An audit with no report yet has none."""
    report = audit.get("report_received_on")
    if report is None:
        return []
    return [{"key": key, "label": label, "due": report + timedelta(days=days), "done_on": audit.get(column)}
            for key, label, days, column in AUDIT_STEPS]


def next_audit_deadline(audit: dict[str, Any], today: date) -> dict[str, Any] | None:
    """The first deadline not done yet, with the days left (negative when late); None when every one is done."""
    for d in audit_deadlines(audit):
        if d["done_on"] is None:
            return {**d, "days_left": (d["due"] - today).days}
    return None


def due_audit_deadlines(audits: list[dict[str, Any]], today: date, within_days: int) -> list[dict[str, Any]]:
    """The morning reminder's audit lines: for each audit given (report received, not closed), its next deadline
    when it is within ``within_days`` of ``today`` or late, most late first."""
    out = []
    for a in audits:
        d = next_audit_deadline(a, today)
        if d is None or d["days_left"] > within_days:
            continue
        out.append({"audit_id": str(a.get("audit_id") or a.get("id")), "kind": a.get("kind"),
                    "title": a.get("title"), "auditor": a.get("auditor"), "key": d["key"], "step": d["label"],
                    "due": d["due"], "days_left": d["days_left"]})
    out.sort(key=lambda r: (r["due"], (r["title"] or "").lower(), r["audit_id"]))
    return out


def deadline_state(due: date, done_on: date | None, today: date) -> str:
    """"on time" (done by the due day), "late" (done after it, or not done and past it) or "not yet"."""
    if done_on is not None:
        return "on time" if done_on <= due else "late"
    return "late" if due < today else "not yet"


def capa_source_text(c: dict[str, Any]) -> str:
    """"from D001/2026" or "from Audit Partner Pharma 2026, observation 2" (capaSourceText on the web)."""
    if c.get("source") == "deviation":
        return f"from {c.get('deviation_ref') or 'a deviation'}"
    number = c.get("observation_number")
    return f"from Audit {c.get('audit_title') or ''}, observation {number if number is not None else '?'}"
