"""PHAROS packs on request: a PSUR pack for one ingredient, or an inspection pack (the QPPV plan, phase 15).

    python -m collectors.report_pack [--dry-run]     build the oldest waiting request, if any
    python -m collectors.report_pack --waiting       print how many requests wait (the workflow's gate)

His decision (6 Nov 2026): a pack is asked for with a button on Reports (``request_report()``, migration 0048)
and built within four hours. The step "Packs on request" of ``.github/workflows/collect.yml`` runs this at the
end of every collection run (never a backfill), ONE request per run, under a time budget of 15 minutes: a pack
not finished in time waits for the next run with a note; after three tries it is marked failed. Every failure is
recorded on the request (``error``) and never stops the run.

A pack is read from the same database functions as the weekly report (``collectors/report_weekly.py``), in
chunks of at most 366 days (the most each function answers), so the pack, the weekly report and the screens
never disagree:

  ingredient_screen(), ingredient_papers(), paper_state()   §3 regulatory actions, §11 literature (0039, 0044)
  label_changes()                                            §4 label changes, with the gap to our label (0043)
  finding_state()                                            the five-day clock, the authority reports and the
                                                             signal of every finding (0041, 0042, 0050)
  screening_log()                                            the screening annex / the screening log (0040)

PSUR pack (report_templates/psur.html and its Excel sheets): the EURD row and its interval; §3 regulatory actions
(the findings by country, with decisions and the reports to the authority); §4 label changes (with the gap to our
label); §11 literature (possible case reports first); §15–16 signals (stages, outcomes, steps); the findings that
do not concern us, counted (and listed in the Excel file); the screening annex.

Inspection pack (report_templates/inspection.html and its sheets): coverage (her pages and whether the app reads
them), the screening log, the decisions and the signatures, the reports to the authority, the weekly reports with
their SHA-256 and signatures, the archive checks, the audit log counted per table, and the people and their roles.

Both are printed by Playwright (A4) like the weekly report, archived with ``put_named(revise=True)`` under
``reports/packs/<kind>/<request id>/`` with the SHA-256 of each file stored on the request, and the person who
asked (and every administrator) is told on Telegram through the weekly report's sender (dry-run aware).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable

from collectors import report_weekly as rw
from collectors.report import (CAIRO, CREDIT, PAGE, SATO_LOGO, XLSX_MIME, _env, build_pdf, copyright_line,
                               logo_data_uri, render_footer, xlsx_sheet, xlsx_summary, xlsx_workbook)
from collectors.report_weekly import (DECISION_LABEL, HERS, KIND_LABEL, OTHERS, SEARCHES_SQL, SIGNAL_OUTCOME_LABEL,
                                      SIGNAL_STAGE_LABEL, as_day, cairo_day, cairo_time, day_text, plural)

log = logging.getLogger("collectors.report_pack")

KINDS = ("psur", "inspection")
NAME = {"psur": "PSUR pack", "inspection": "Inspection pack"}
FOOTER_NAME = {"psur": "PSUR pack", "inspection": "Inspection"}   # the running foot fits the monthly one's length
TITLE = {"psur": "PHAROS — PSUR pack", "inspection": "PHAROS — Inspection pack"}
MAX_CHUNK_DAYS = 366          # the most days ingredient_screen() and screening_log() answer in one call
BUDGET_S = 15 * 60            # one request per run, at most this long
MAX_ATTEMPTS = 3              # builds cut short before the request is marked failed
BATCH = 200                   # issue or paper ids per finding_state() / paper_state() call
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
REPORTS_URL = "https://pharos-satopharma.pages.dev/reports"
ROLE_LABEL = {"admin": "Administrator", "reviewer": "Reviewer", "reader": "Reader"}
MEANING_LABEL = {"reviewed": "Reviewed", "approved": "Approved"}
SIGNAL_STEP_LABEL = {"opened": "Opened the signal", "notice_linked": "Added a notice", "validated": "Validated",
                     "not_validated": "Closed as not validated", "prioritised": "Changed the priority",
                     "assigned": "Assigned an owner", "assessed": "Recorded the assessment",
                     "action_done": "Closed with the action done", "reopened": "Reopened", "note": "Added a note"}
SIGNAL_PRIORITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}
PAGE_KIND = rw.PAGE_KIND


class OutOfTime(Exception):
    """The time budget of the request ran out: it waits for the next run."""


# ───────────────────────────── the days ─────────────────────────────

def chunks(start: date, end: date, days: int = MAX_CHUNK_DAYS) -> list[tuple[date, date]]:
    """The days from ``start`` to ``end`` (both included) in consecutive pieces of at most ``days`` days."""
    if end < start:
        raise ValueError(f"{end} is before {start}")
    out = []
    a = start
    while a <= end:
        b = min(end, a + timedelta(days=days - 1))
        out.append((a, b))
        a = b + timedelta(days=1)
    return out


def days_label(start: date, end: date) -> str:
    """"2 Dec 2024 – 6 Nov 2026"."""
    return f"{day_text(start)} – {day_text(end)}"


@dataclass(frozen=True)
class Period:
    kind: str
    start: date
    end: date

    @property
    def name(self) -> str:
        return NAME[self.kind]

    @property
    def label(self) -> str:
        return days_label(self.start, self.end)

    @property
    def footer(self) -> str:
        """The running foot: "PSUR pack · 2 Dec 2024 – 6 Nov 2026", "Inspection · 30 Sep 2025 – 30 Sep 2026"
        (never longer than the monthly one's, so it is never cut)."""
        return f"{FOOTER_NAME[self.kind]} · {self.label}"

    def bounds_utc(self) -> tuple[datetime, datetime]:
        """The first day's 00:00 to the day after the last, Cairo time, as UTC instants: [a, b)."""
        a = datetime.combine(self.start, dtime(0), CAIRO).astimezone(timezone.utc)
        b = datetime.combine(self.end + timedelta(days=1), dtime(0), CAIRO).astimezone(timezone.utc)
        return a, b


# The EURD interval, as web/src/lib/psur.ts works it out (intervalFor).
def frequency_months(frequency: str | None) -> int | None:
    """"7 years" → 84, "6 months" → 6; None for anything else."""
    import re

    m = re.match(r"^\s*(\d{1,2})\s*(year|month)s?\b", frequency or "", re.I)
    if not m:
        return None
    return int(m.group(1)) * (12 if m.group(2).lower() == "year" else 1)


def _add_months(day: date, months: int) -> date:
    import calendar

    y, m = divmod(day.month - 1 + months, 12)
    y, m = day.year + y, m + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def interval_for(dlp: Any, frequency: str | None) -> tuple[date, date] | None:
    """The reporting interval that ends at the data lock point: the day after the DLP one frequency earlier, to
    the DLP itself."""
    d, months = as_day(dlp), frequency_months(frequency)
    if not d or not months:
        return None
    return _add_months(d, -months) + timedelta(days=1), d


class Budget:
    """The time budget of one request: ``check()`` raises OutOfTime once it is spent."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, seconds: float = BUDGET_S) -> None:
        self.clock = clock
        self.deadline = clock() + seconds

    def check(self) -> None:
        if self.clock() >= self.deadline:
            raise OutOfTime()


def _no_check() -> None:
    return None


# ───────────────────────────── reading, in chunks ─────────────────────────────

def _batched(db: Any, sql: str, key: str, ids: list[str]) -> dict:
    out: dict = {}
    for k in range(0, len(ids), BATCH):
        row = db.fetchone(sql, {"ids": ids[k:k + BATCH]}) or {}
        out.update(row.get(key) or {})
    return out


def _paper_states(db: Any, ids: list[str]) -> dict:
    out: dict = {}
    for k in range(0, len(ids), BATCH):
        rows = db.fetchall("select paper_state(%(ids)s::uuid[]) as state", {"ids": ids[k:k + BATCH]})
        out.update((rows[0].get("state") if rows else None) or {})
    return out


def finding_states(db: Any, issue_ids: list[str]) -> dict:
    """The clock, the report to the authority and the signal of every finding (finding_state, 0041, 0042)."""
    return _batched(db, "select finding_state(%(ids)s::uuid[]) as f", "f", sorted(set(issue_ids)))


def merge_regulators(into: dict[str, dict], regulators: list[dict]) -> None:
    """ingredient_screen()'s regulators of one chunk added to those of the chunks before: reads summed, each
    notice once, the pages and sources as the latest chunk lists them."""
    for r in regulators:
        have = into.get(r["id"])
        if have is None:
            into[r["id"]] = {**r, "mentions": [], "runs": 0, "ok": 0, "failed": 0}
            have = into[r["id"]]
        else:
            have.update({k: r[k] for k in ("pages", "sources", "unread_page", "hers") if k in r})
        for k in ("runs", "ok", "failed"):
            have[k] = int(have.get(k) or 0) + int(r.get(k) or 0)
        seen = {m.get("document_id") for m in have["mentions"]}
        have["mentions"].extend(m for m in r.get("mentions") or [] if m.get("document_id") not in seen)


def sum_screening_logs(logs: list[list[dict]]) -> list[dict]:
    """screening_log() of every chunk, one row per source: counts summed, the latest read and failure kept."""
    out: dict[str, dict] = {}
    for rows in logs:
        for r in rows:
            have = out.get(r["source_id"])
            if have is None:
                out[r["source_id"]] = dict(r)
                continue
            for k in ("runs", "ok_runs", "failed_runs", "items_seen", "items_new", "items_matched"):
                have[k] = int(have.get(k) or 0) + int(r.get(k) or 0)
            if r.get("last_run") and (not have.get("last_run") or str(r["last_run"]) > str(have["last_run"])):
                have["last_run"] = r["last_run"]
            if r.get("last_failure"):
                have["last_failure"] = r["last_failure"]
            have["enabled"] = r.get("enabled")
    return sorted(out.values(), key=lambda r: (str(r.get("country") or "").casefold(), r["source_id"]))


def _log_chunks(db: Any, period: Period, check: Callable[[], None]) -> list[list[dict]]:
    logs = []
    for f, t in chunks(period.start, period.end):
        check()
        logs.append(db.fetchall("select * from screening_log(%(f)s, %(t)s)", {"f": f, "t": t}))
    return logs


PAPERS_SQL = """select document_id::text as document_id, title, lang, journal, day, pubmed_url, pmc_url,
                       by_class, is_backfill, first_seen_at
                  from ingredient_papers(%(i)s::uuid, %(f)s, %(t)s)"""

EURD_SQL = """select eurd_id, substance, combination, frequency, dlp, submission_date, next_dlp,
                     next_submission_date, generics_psur_required, procedure, next_procedure, lead_ms,
                     list_version, list_date
                from eurd_entry where ingredient_id = %(i)s::uuid
               order by combination, eurd_id"""


def gather_psur(db: Any, req: dict, check: Callable[[], None] = _no_check) -> dict:
    """What a PSUR pack is made from, read chunk by chunk through the weekly report's functions."""
    period = Period("psur", as_day(req["from_day"]), as_day(req["to_day"]))
    i = str(req["ingredient_id"])
    ingredient = db.fetchone("select id::text as id, inn_en, atc_code from ingredient where id = %(i)s::uuid",
                             {"i": i})
    if not ingredient:
        raise LookupError("That ingredient is no longer on the watchlist.")
    regulators: dict[str, dict] = {}
    papers: dict[str, dict] = {}
    changes: dict[str, dict] = {}
    literature = {"papers": 0, "by_name": 0, "by_class": 0, "pubmed": 0, "pmc": 0}
    by_query: dict[str, dict] = {}
    logs = []
    for f, t in chunks(period.start, period.end):
        check()
        p = {"i": i, "f": f, "t": t}
        screen = (db.fetchone("select ingredient_screen(%(i)s::uuid, %(f)s, %(t)s) as screen", p) or {}).get(
            "screen") or {}
        merge_regulators(regulators, screen.get("regulators") or [])
        lit = screen.get("literature") or {}
        for k in literature:
            literature[k] += int(lit.get(k) or 0)
        for q in lit.get("by_query") or []:
            have = by_query.setdefault(q.get("query"), {"query": q.get("query"), "pubmed": 0, "pmc": 0})
            have["pubmed"] += int(q.get("pubmed") or 0)
            have["pmc"] += int(q.get("pmc") or 0)
        for row in db.fetchall(PAPERS_SQL, p):
            papers.setdefault(str(row["document_id"]), row)
        for c in (db.fetchone("select label_changes(%(i)s::uuid, %(f)s, %(t)s) as changes", p) or {}).get(
                "changes") or []:
            changes.setdefault(str(c.get("change_id")), c)
        logs.append(db.fetchall("select * from screening_log(%(f)s, %(t)s)", {"f": f, "t": t}))
    check()
    states = _paper_states(db, list(papers))
    issue_ids = ([str(m["issue_id"]) for r in regulators.values() for m in r["mentions"] if m.get("issue_id")]
                 + [str(c["issue_id"]) for c in changes.values() if c.get("issue_id")]
                 + [str(s["issue_id"]) for s in states.values() if (s or {}).get("issue_id")])
    findings = finding_states(db, issue_ids)
    mlm = db.fetchall("select mlm_monitored(%(i)s::uuid) as monitored", {"i": i})
    return {"period": period, "request": req, "ingredient": ingredient,
            "eurd": db.fetchall(EURD_SQL, {"i": i}),
            "regulators": regulators, "papers": list(papers.values()), "states": states,
            "label_changes": list(changes.values()), "literature": literature, "by_query": by_query,
            "searches": db.fetchall(SEARCHES_SQL, {"i": i}), "findings": findings,
            "mlm": bool(mlm[0]["monitored"]) if mlm else None, "log": sum_screening_logs(logs)}


# Every signature of the days, with the fingerprint of its record now, as record_fingerprint() (0047, 0048)
# computes it for a signer.
SIGNATURES_SQL = """select so.signed_at, so.record_kind::text as record_kind, so.record_id::text as record_id,
                      so.meaning::text as meaning, so.signed_name, so.signed_role::text as signed_role, so.comment,
                      so.record_sha256, w.week_start, rq.kind as pack_kind, rq.from_day, rq.to_day,
                      m.month, sg.ref as signal_ref,
                      case so.record_kind::text
                        when 'weekly_report' then encode(sha256(convert_to(w.pdf_sha256 || ':' || w.xlsx_sha256, 'UTF8')), 'hex')
                        when 'pack' then encode(sha256(convert_to(rq.pdf_sha256 || ':' || rq.xlsx_sha256, 'UTF8')), 'hex')
                        when 'monthly_report' then encode(sha256(convert_to(m.pdf_sha256 || ':' || m.xlsx_sha256, 'UTF8')), 'hex')
                        -- as record_fingerprint() in 0048: this connection has no session, so it cannot call it
                        when 'signal' then encode(sha256(convert_to(jsonb_build_object(
                                 'signal', to_jsonb(sg) - 'updated_at',
                                 'events', (select coalesce(jsonb_agg(e.id order by e.created_at, e.id), '[]')
                                              from signal_event e where e.signal_id = sg.id),
                                 'issues', (select coalesce(jsonb_agg(si.issue_id order by si.issue_id), '[]')
                                              from signal_issue si where si.signal_id = sg.id)
                               )::text, 'UTF8')), 'hex')
                      end as fingerprint_now
                 from sign_off so
                 left join weekly_report w on so.record_kind::text = 'weekly_report' and w.id = so.record_id
                 left join report_request rq on so.record_kind::text = 'pack' and rq.id = so.record_id
                 left join monthly_report m on so.record_kind::text = 'monthly_report' and m.id = so.record_id
                 left join signal sg on so.record_kind::text = 'signal' and sg.id = so.record_id
                where so.signed_at >= %(a)s and so.signed_at < %(b)s
                order by so.signed_at, so.id"""


def gather_inspection(db: Any, req: dict, check: Callable[[], None] = _no_check) -> dict:
    """What an inspection pack is made from: the screening log chunk by chunk, and the records of the days."""
    period = Period("inspection", as_day(req["from_day"]), as_day(req["to_day"]))
    a, b = period.bounds_utc()
    span = {"a": a, "b": b, "f": period.start, "t": period.end}
    logs = _log_chunks(db, period, check)
    check()
    return {
        "period": period, "request": req, "log": sum_screening_logs(logs),
        "regulators": db.fetchall("select id, name, country_name, country_code, homepage from regulator"),
        "pages": db.fetchall(
            """select id::text as id, regulator_id, kind::text as kind, sort, label, url, read_by, partial, note
                 from regulator_page"""),
        "sources": db.fetchall(
            """select id, regulator_id, kind::text as kind, channel::text as channel, url, page_url, enabled,
                      health::text as health, notes
                 from source"""),
        "runs": db.fetchone(
            """select count(*) as runs, count(*) filter (where ok) as ok_runs
                 from run where started_at >= %(a)s and started_at < %(b)s""", span) or {},
        "decisions": db.fetchall(
            """select re.created_at, re.from_status::text as from_status, re.to_status::text as to_status,
                      re.comment, p.full_name as person, i.title, re.issue_id::text as issue_id
                 from review_event re
                 join person p on p.id = re.person_id
                 join issue i on i.id = re.issue_id
                where re.created_at >= %(a)s and re.created_at < %(b)s
                order by re.created_at, re.id""", span),
        "signatures": db.fetchall(SIGNATURES_SQL, span),
        "sent": db.fetchall(
            """select ar.sent_on, ar.authority, ar.reference, ar.note, p.full_name as person, i.title,
                      ar.withdrawn_at, ar.withdraw_reason, wp.full_name as withdrawn_by
                 from authority_report ar
                 join person p on p.id = ar.person_id
                 join issue i on i.id = ar.issue_id
                 left join person wp on wp.id = ar.withdrawn_by
                where ar.sent_on >= %(f)s and ar.sent_on <= %(t)s
                order by ar.sent_on, lower(i.title), ar.id""", span),
        "weekly": db.fetchall(
            """select w.id::text as id, w.week_start, w.week_end, w.pdf_sha256, w.xlsx_sha256, w.made_at,
                      w.git_sha, w.made_by_run,
                      encode(sha256(convert_to(w.pdf_sha256 || ':' || w.xlsx_sha256, 'UTF8')), 'hex') as fingerprint,
                      coalesce((select json_agg(json_build_object(
                                  'name', so.signed_name, 'role', so.signed_role, 'meaning', so.meaning,
                                  'at', so.signed_at, 'sha', so.record_sha256) order by so.signed_at, so.id)
                                  from sign_off so
                                 where so.record_kind::text = 'weekly_report' and so.record_id = w.id), '[]') as signatures
                 from weekly_report w
                where w.week_start >= %(f)s and w.week_start <= %(t)s
                order by w.week_start""", span),
        "archive_checks": db.fetchall(
            """select checked_at, sampled, mismatched, missing, git_sha
                 from archive_check where checked_at >= %(a)s and checked_at < %(b)s
                order by checked_at""", span),
        "audit": db.fetchall(
            """select table_name, action, count(*) as n
                 from audit_log where at >= %(a)s and at < %(b)s
                group by table_name, action
                order by table_name, action""", span),
        "people": db.fetchall(
            """select full_name, role::text as role, active, telegram_chat_id is not null as telegram, created_at
                 from person
                order by active desc, role, lower(full_name)"""),
    }


# ───────────────────────────── worded once, for the PDF and the Excel file ─────────────────────────────

def answer_text(c: dict) -> str:
    """A country's answer over the days of the pack (answer_of in report_weekly)."""
    a = c["answer"]
    if a == "mentioned":
        return f"Mentioned in {plural(len(c['mentions']), 'notice', 'notices')}"
    if a == "not_read":
        return "Not read in these days"
    if a == "failed":
        return f"{c['failed']} of {plural(c['runs'], 'read', 'reads')} failed"
    if a == "unread_page":
        return "A page of hers is not read by the app"
    return "Nothing found"


def _sent_text(f: dict | None) -> str:
    s = (f or {}).get("sent") or None
    if not s:
        return ""
    out = f"Sent to the authority {day_text(s.get('on'))}"
    if s.get("reference"):
        out += f" · {s['reference']}"
    return out


def _clock(f: dict | None) -> dict:
    cells = rw.clock_cells(f)
    return {"due": cells["due"], "sent_text": _sent_text(f), "signal": cells["signal"]}


def _signals(findings: dict, titles: dict[str, str]) -> list[dict]:
    """Each signal once, from the findings that belong to it (finding_state().signal, 0042)."""
    out: dict[str, dict] = {}
    for issue_id, f in findings.items():
        s = (f or {}).get("signal") or None
        if not s:
            continue
        have = out.get(str(s.get("id")))
        if have is None:
            stage = s.get("stage") or ""
            have = out[str(s.get("id"))] = {
                "ref": s.get("ref") or "", "title": s.get("title") or "",
                "stage": SIGNAL_STAGE_LABEL.get(stage, stage),
                "closed": stage == "closed",
                "priority": SIGNAL_PRIORITY_LABEL.get(s.get("priority") or "", ""),
                "outcome": (SIGNAL_OUTCOME_LABEL.get(s.get("outcome") or "", s.get("outcome") or "")).capitalize(),
                "next_due": day_text(s.get("next_due")) if stage != "closed" else "",
                "overdue": bool(s.get("overdue")) and stage != "closed",
                "owner": s.get("owner") or "",
                "opened": cairo_time(s.get("opened_at")), "opened_by": s.get("opened_by") or "",
                "steps": [{"step": SIGNAL_STEP_LABEL.get(e.get("step") or "", e.get("step") or ""),
                           "person": e.get("person") or "", "at": cairo_time(e.get("at")),
                           "comment": e.get("comment") or ""} for e in s.get("steps") or []],
                "findings": [],
                "sort": str(s.get("opened_at") or ""),
            }
        have["findings"].append(titles.get(issue_id, ""))
    signals = sorted(out.values(), key=lambda s: (s["sort"], s["ref"]))
    for s in signals:
        s["findings"] = sorted(t for t in s["findings"] if t)
    return signals


def _eurd(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        iv = interval_for(r.get("dlp"), r.get("frequency"))
        out.append({"substance": r.get("substance") or "", "combination": bool(r.get("combination")),
                    "frequency": r.get("frequency") or "", "dlp": day_text(r.get("dlp")),
                    "submission": day_text(r.get("submission_date")), "next_dlp": day_text(r.get("next_dlp")),
                    "next_submission": day_text(r.get("next_submission_date")),
                    "generics": "" if r.get("generics_psur_required") is None
                    else ("Yes" if r["generics_psur_required"] else "No"),
                    "procedure": r.get("procedure") or "", "lead": r.get("lead_ms") or "",
                    "list": (r.get("list_version") or "") + (f", {day_text(r['list_date'])}" if r.get("list_date")
                                                             else ""),
                    "interval": days_label(*iv) if iv else ""})
    return out


def _annex(rows: list[dict]) -> list[dict]:
    return [{"country": r.get("country") or "", "authority": r.get("regulator") or "",
             "source": r["source_id"], "kind": KIND_LABEL.get(r.get("source_kind") or "", r.get("source_kind") or ""),
             "enabled": bool(r.get("enabled")), "runs": int(r.get("runs") or 0),
             "failed": int(r.get("failed_runs") or 0), "seen": int(r.get("items_seen") or 0),
             "matched": int(r.get("items_matched") or 0), "last_run": cairo_time(r.get("last_run")),
             "why": (r.get("last_failure") or "")[:300]} for r in rows]


def _asked(req: dict) -> str:
    who = req.get("requested_by_name") or ""
    at = cairo_time(req.get("requested_at"))
    return ", ".join(x for x in (who, at) if x)


def assemble_psur(raw: dict, made_at: datetime | None = None) -> dict:
    made_at = made_at or datetime.now(timezone.utc)
    period: Period = raw["period"]
    findings = raw.get("findings") or {}
    ing = raw["ingredient"]
    hers, others = rw.country_answers(list(raw["regulators"].values()))
    titles: dict[str, str] = {}

    # §3 regulatory actions: the authorities' notices, by country; what does not concern us goes apart.
    actions, countries, not_relevant = [], [], []
    for group, cs in ((HERS, hers), (OTHERS, others)):
        for c in cs:
            countries.append({"group": group, "country": c["country"], "answer": c["answer"],
                              "answer_text": answer_text(c)})
            keep = []
            for m in c["mentions"]:
                row = {**rw._mention(m, findings), **_clock(findings.get(str(m.get("issue_id") or "")))}
                if m.get("issue_id"):
                    titles[str(m["issue_id"])] = row["title"]
                if m.get("issue_status") == "not_relevant":
                    not_relevant.append({"section": "§3 Regulatory actions", "country": c["country"], **row})
                else:
                    keep.append(row)
            if keep:
                actions.append({"group": group, "country": c["country"],
                                "authorities": " · ".join(r["name"] for r in c["regulators"]), "mentions": keep})

    # §4 label changes, with the gap to our label (0043).
    labels = []
    for ch in sorted(raw["label_changes"], key=lambda x: (str(x.get("detected_day") or ""), str(x.get("change_id"))),
                     reverse=True):
        row = {**rw._label_change(ch, findings), **_clock(findings.get(str(ch.get("issue_id") or "")))}
        if ch.get("issue_id"):
            titles[str(ch["issue_id"])] = row["title"]
        if ch.get("issue_status") == "not_relevant":
            not_relevant.append({"section": "§4 Label changes", **row})
        else:
            labels.append(row)

    # §11 literature: possible case reports first, then the newest.
    states = raw.get("states") or {}
    papers = []
    raw_papers = sorted(raw["papers"], key=lambda x: str(x.get("first_seen_at") or ""), reverse=True)
    raw_papers.sort(key=lambda x: str(as_day(x.get("day")) or ""), reverse=True)
    for p in raw_papers:
        st = states.get(str(p.get("document_id"))) or {}
        row = rw._paper(p, st)
        if st.get("issue_id"):
            titles[str(st["issue_id"])] = row["title"]
        if st.get("issue_status") == "not_relevant":
            not_relevant.append({"section": "§11 Literature", **row})
        else:
            papers.append(row)
    papers.sort(key=lambda x: not x["case_report"])          # possible case reports first, then the newest
    lit = raw["literature"]
    searches = sorted(raw.get("searches") or [], key=lambda s: (s["kind"] != "name", s["query"]))
    by_query = raw.get("by_query") or {}

    signals = _signals(findings, titles)
    eurd = _eurd(raw.get("eurd") or [])
    annex = _annex(raw["log"])
    nr_counts = defaultdict(int)
    for r in not_relevant:
        nr_counts[r["section"]] += 1
    mentions = [m for a in actions for m in a["mentions"]]
    summary = [
        ("Pack", TITLE["psur"]),
        ("Ingredient", ing["inn_en"] + (f" ({ing['atc_code']})" if ing.get("atc_code") else "")),
        ("Days (Cairo time)", period.label),
        ("EURD interval", "; ".join(f"{e['interval']} ({e['frequency']})" for e in eurd if e["interval"])
         or ("No interval in the EURD row" if eurd else "Not in EMA's EURD list")),
        ("Asked for by", _asked(raw["request"])),
        ("Made (Cairo)", cairo_time(made_at)),
        ("§3 Regulatory actions (notices)", len(mentions)),
        ("Of them, concerns us", sum(1 for m in mentions if m["status"] == "relevant")),
        ("Of them, no decision yet", sum(1 for m in mentions if m["awaiting"])),
        ("Sent to the authority", sum(1 for m in mentions + labels if m["sent_text"])),
        ("§4 Label changes", len(labels)),
        ("§11 Papers in PubMed and PubMed Central", len(papers)),
        ("Of them, possible case reports", sum(1 for p in papers if p["case_report"])),
        ("§15–16 Signals", len(signals)),
        ("Of them, still open", sum(1 for s in signals if not s["closed"])),
        ("Findings that do not concern us", len(not_relevant)),
        ("Reads of every source", sum(r["runs"] for r in annex)),
        ("Reads that failed", sum(r["failed"] for r in annex)),
    ]
    figures = [("Regulatory actions", len(mentions)), ("Label changes", len(labels)), ("Papers", len(papers)),
               ("Signals", len(signals))]
    return {"kind": "psur", "period": period, "made_at": made_at, "title": TITLE["psur"],
            "ingredient": {"name": ing["inn_en"], "atc": ing.get("atc_code") or ""},
            "asked": _asked(raw["request"]), "summary": summary, "figures": figures, "eurd": eurd,
            "countries": countries, "actions": actions, "labels": labels,
            "literature": {"papers": papers, "case_reports": sum(1 for p in papers if p["case_report"]),
                           "counts": lit, "mlm": rw.MLM_TEXT.get(raw.get("mlm"), ""),
                           "searches": [{"query": s["query"],
                                         "kind": "name" if s["kind"] == "name" else "class word",
                                         "pubmed": int((by_query.get(s["query"]) or {}).get("pubmed") or 0),
                                         "pmc": int((by_query.get(s["query"]) or {}).get("pmc") or 0)}
                                        for s in searches]},
            "signals": signals, "not_relevant": not_relevant,
            "not_relevant_counts": [(k, nr_counts[k]) for k in ("§3 Regulatory actions", "§4 Label changes",
                                                                 "§11 Literature")],
            "annex": annex}


def _record_text(s: dict) -> str:
    kind = s.get("record_kind")
    if kind == "weekly_report" and s.get("week_start"):
        return f"Weekly report, {rw.week_label(as_day(s['week_start']))}"
    if kind == "pack" and s.get("pack_kind"):
        return f"{NAME.get(s['pack_kind'], 'Pack')}, {days_label(as_day(s['from_day']), as_day(s['to_day']))}"
    if kind == "monthly_report" and s.get("month"):
        return f"Monthly report, {as_day(s['month']):%B %Y}"
    if kind == "signal" and s.get("signal_ref"):
        return f"Signal {s['signal_ref']}"
    return {"weekly_report": "Weekly report", "pack": "Pack", "monthly_report": "Monthly report",
            "signal": "Signal"}.get(kind or "", kind or "")


def _sig_state(signed: str | None, now: str | None) -> str:
    if not now:
        return "Record not readable"
    return "Matches the file" if signed == now else "File changed since signing"


def assemble_inspection(raw: dict, made_at: datetime | None = None) -> dict:
    made_at = made_at or datetime.now(timezone.utc)
    period: Period = raw["period"]
    sources_by_id = {s["id"]: s for s in raw["sources"]}
    notice_regs = {s["regulator_id"] for s in raw["sources"] if s["kind"] not in ("spc", "literature")}
    paged = {p["regulator_id"] for p in raw["pages"]}
    regs = [r for r in raw["regulators"] if r["id"] in notice_regs or r["id"] in paged]
    hers, _ = rw.country_cards(regs, raw["pages"], raw["sources"])

    # Coverage: every page of hers, and whether the app reads it (pageStatus in horizontal.ts).
    coverage = []
    for c in hers:
        for p in c["pages"]:
            st = rw.page_status(p, sources_by_id)
            coverage.append({"country": c["country"], "label": p["label"], "kind": PAGE_KIND.get(p["kind"], ""),
                             "url": rw.safe_link(p["url"]), "state": st["state"], "status": st["label"],
                             "note": st["note"] or "",
                             "read_by": ", ".join(i for i in p.get("read_by") or [] if i in sources_by_id)})
    annex = _annex(raw["log"])
    decisions = [{"at": cairo_time(d["created_at"]), "title": d["title"] or "",
                  "decision": DECISION_LABEL.get(d["to_status"], d["to_status"]),
                  "before": DECISION_LABEL.get(d["from_status"], d["from_status"]),
                  "person": d["person"], "reason": d["comment"] or ""} for d in raw["decisions"]]
    signatures = [{"at": cairo_time(s["signed_at"]), "record": _record_text(s),
                   "meaning": MEANING_LABEL.get(s["meaning"], s["meaning"]), "name": s["signed_name"],
                   "role": ROLE_LABEL.get(s["signed_role"], s["signed_role"]), "comment": s.get("comment") or "",
                   "sha": s.get("record_sha256") or "",
                   "state": _sig_state(s.get("record_sha256"), s.get("fingerprint_now"))}
                  for s in raw["signatures"]]
    sent = [{"on": day_text(s["sent_on"]), "title": s["title"] or "", "authority": s.get("authority") or "EDA",
             "reference": s.get("reference") or "", "person": s["person"], "note": s.get("note") or "",
             "withdrawn": (f"Withdrawn {cairo_time(s['withdrawn_at'])} by {s.get('withdrawn_by') or ''}: "
                           f"{s.get('withdraw_reason') or ''}") if s.get("withdrawn_at") else ""}
            for s in raw["sent"]]
    weekly = []
    for w in raw["weekly"]:
        sigs = [{"name": g.get("name") or "", "role": ROLE_LABEL.get(g.get("role") or "", g.get("role") or ""),
                 "meaning": MEANING_LABEL.get(g.get("meaning") or "", g.get("meaning") or ""),
                 "at": cairo_time(g.get("at")), "state": _sig_state(g.get("sha"), w.get("fingerprint"))}
                for g in (w.get("signatures") or [])]
        weekly.append({"week": rw.week_label(as_day(w["week_start"])), "made": cairo_time(w.get("made_at")),
                       "pdf_sha256": w.get("pdf_sha256") or "", "xlsx_sha256": w.get("xlsx_sha256") or "",
                       "git_sha": w.get("git_sha") or "", "run": rw.safe_link(w.get("made_by_run")) or "",
                       "signatures": sigs,
                       "signed": "; ".join(f"{g['meaning']} by {g['name']} ({g['role']}), {g['at']} — {g['state']}"
                                           for g in sigs) or "Not signed"})
    checks = [{"at": cairo_time(c["checked_at"]), "sampled": int(c.get("sampled") or 0),
               "mismatched": int(c.get("mismatched") or 0), "missing": int(c.get("missing") or 0),
               "result": "Every file matched its SHA-256" if not (c.get("mismatched") or c.get("missing"))
               else "Files did not match or were missing", "git_sha": c.get("git_sha") or ""}
              for c in raw["archive_checks"]]
    audit = [{"table": a["table_name"], "action": str(a["action"]).capitalize(), "n": int(a["n"])}
             for a in raw["audit"]]
    people = [{"name": p["full_name"], "role": ROLE_LABEL.get(p["role"], p["role"]),
               "active": "Active" if p.get("active") else "Switched off",
               "telegram": "Linked" if p.get("telegram") else "", "added": day_text(cairo_day(p.get("created_at")))}
              for p in raw["people"]]
    runs = raw.get("runs") or {}
    read_pages = sum(1 for c in coverage if c["state"] == "read")
    summary = [
        ("Pack", TITLE["inspection"]),
        ("Days (Cairo time)", period.label),
        ("Asked for by", _asked(raw["request"])),
        ("Made (Cairo)", cairo_time(made_at)),
        ("Her pages", len(coverage)),
        ("Of them, read by the app", read_pages),
        ("Of them, partly read", sum(1 for c in coverage if c["state"] == "partial")),
        ("Of them, not read: checked by hand", sum(1 for c in coverage if c["state"] == "unread")),
        ("Collection runs", int(runs.get("runs") or 0)),
        ("Of them, completed without error", int(runs.get("ok_runs") or 0)),
        ("Reads of every source", sum(r["runs"] for r in annex)),
        ("Reads that failed", sum(r["failed"] for r in annex)),
        ("Decisions", len(decisions)),
        ("Signatures", len(signatures)),
        ("Reports to the authority", sum(1 for s in sent if not s["withdrawn"])),
        ("Weekly reports", len(weekly)),
        ("Archive checks", len(checks)),
        ("Archive checks that found a problem", sum(1 for c in checks if c["mismatched"] or c["missing"])),
        ("Changes in the audit log", sum(a["n"] for a in audit)),
        ("People", len(people)),
    ]
    figures = [("Her pages read", f"{read_pages} / {len(coverage)}"), ("Decisions", len(decisions)),
               ("Weekly reports", len(weekly)), ("Signatures", len(signatures))]
    return {"kind": "inspection", "period": period, "made_at": made_at, "title": TITLE["inspection"],
            "asked": _asked(raw["request"]), "summary": summary, "figures": figures, "coverage": coverage,
            "annex": annex, "decisions": decisions, "signatures": signatures, "sent": sent, "weekly": weekly,
            "checks": checks, "audit": audit, "people": people}


# ───────────────────────────── Excel ─────────────────────────────

PSUR_SHEETS = ("Summary", "EURD", "§3 Regulatory actions", "§3 Countries", "§4 Label changes", "§11 Literature",
               "§11 Searches", "§15-16 Signals", "Not relevant", "Screening annex")
INSPECTION_SHEETS = ("Summary", "Coverage", "Screening log", "Decisions", "Signatures", "Authority reports",
                     "Weekly reports", "Archive checks", "Audit log", "People and roles")


def _decision_cells(m: dict) -> list:
    return [m["decision"], m["decided_by"], m["decided_at"], m["reason"]]


def _annex_sheet(wb, title: str, annex: list[dict]) -> None:
    xlsx_sheet(wb, title,
               ["Country", "Authority", "Source", "Kind", "Switched on", "Reads", "Failed", "Items read",
                "Matched", "Last read (Cairo)", "Last failure"],
               [[r["country"], r["authority"], r["source"], r["kind"], "yes" if r["enabled"] else "no", r["runs"],
                 r["failed"], r["seen"], r["matched"], r["last_run"], r["why"]] for r in annex],
               [18, 28, 22, 20, 10, 8, 8, 10, 9, 18, 50])


def build_psur_xlsx(data: dict) -> bytes:
    import io

    wb = xlsx_workbook(f"{data['title']}, {data['ingredient']['name']}, {data['period'].label}")
    xlsx_summary(wb.active, data["summary"] + [(f"Not relevant, {k}", n) for k, n in data["not_relevant_counts"]])
    xlsx_sheet(wb, "EURD",
               ["Substance", "Combination", "Frequency", "Data lock point", "Interval", "Submission", "Next DLP",
                "Next submission", "Generics submit PSURs", "Procedure", "Lead member state", "List"],
               [[e["substance"], "yes" if e["combination"] else "", e["frequency"], e["dlp"], e["interval"],
                 e["submission"], e["next_dlp"], e["next_submission"], e["generics"], e["procedure"], e["lead"],
                 e["list"]] for e in data["eurd"]],
               [34, 12, 12, 14, 28, 14, 14, 14, 12, 24, 14, 30])
    xlsx_sheet(wb, "§3 Regulatory actions",
               ["Group", "Country", "Authority", "Date", "Notice (original title)", "Type", "Link", "Words matched",
                "By class", "History", "Decision", "Decided by", "Decided (Cairo)", "Reason", "Due to the authority",
                "Sent to the authority", "Signal"],
               [[a["group"], a["country"], m["authority"], m["day"], m["title"], m["doc_type"],
                 m["link"] or ("By e-mail: open it in PHAROS" if m["by_email"] else ""), m["words"],
                 "yes" if m["by_class"] else "", "yes" if m["history"] else "", *_decision_cells(m), m["due"],
                 m["sent_text"], m["signal"]] for a in data["actions"] for m in a["mentions"]],
               [18, 18, 24, 14, 60, 16, 50, 30, 9, 9, 20, 20, 18, 40, 18, 34, 40], links=True)
    xlsx_sheet(wb, "§3 Countries", ["Group", "Country", "Answer over these days"],
               [[c["group"], c["country"], c["answer_text"]] for c in data["countries"]], [20, 24, 40])
    xlsx_sheet(wb, "§4 Label changes",
               ["Detected", "Country", "Authority", "Product", "Holder", "Reference product", "Label dated",
                "Sections changed", "Our label", "Gap to our label", "Title", "Link", "Decision", "Decided by",
                "Decided (Cairo)", "Reason", "Sent to the authority", "Signal"],
               [[m["day"], m["country"], m["authority"], m["product"], m["mah"], "yes" if m["reference"] else "",
                 m["label_day"], m["sections"], m["our_label"], m["gap_summary"], m["title"], m["link"] or "",
                 *_decision_cells(m), m["sent_text"], m["signal"]] for m in data["labels"]],
               [18, 16, 22, 30, 24, 10, 14, 24, 28, 34, 50, 44, 20, 20, 18, 40, 34, 40], links=True)
    xlsx_sheet(wb, "§11 Literature",
               ["Date", "Title", "Journal", "PubMed", "PubMed Central", "By class", "History", "Possible case report",
                "Day zero", "15 days", "90 days", "Decision", "Decided by", "Decided (Cairo)", "Reason"],
               [[p["day"], p["title"], p["journal"], p["pubmed"] or "", p["pmc"] or "", "yes" if p["by_class"] else "",
                 "yes" if p["history"] else "", f"yes, {p['case_reason']}" if p["case_report"] else "",
                 p["day_zero"] if p["case_report"] else "", p["due_serious"] if p["case_report"] else "",
                 p["due_nonserious"] if p["case_report"] else "", *_decision_cells(p)]
                for p in data["literature"]["papers"]],
               [14, 70, 30, 40, 46, 9, 9, 30, 14, 14, 14, 20, 20, 18, 40], links=True)
    xlsx_sheet(wb, "§11 Searches", ["Search", "Searched as", "PubMed", "PubMed Central"],
               [[s["query"], s["kind"], s["pubmed"], s["pmc"]] for s in data["literature"]["searches"]],
               [36, 14, 10, 16])
    xlsx_sheet(wb, "§15-16 Signals",
               ["Signal", "Title", "Opened (Cairo)", "Opened by", "Stage", "Priority", "Outcome", "Next step due",
                "Late", "Owner", "Findings", "Steps"],
               [[s["ref"], s["title"], s["opened"], s["opened_by"], s["stage"], s["priority"], s["outcome"],
                 s["next_due"], "yes" if s["overdue"] else "", s["owner"], "; ".join(s["findings"]),
                 "\n".join(f"{e['at']} · {e['step']} · {e['person']}" + (f" · {e['comment']}" if e["comment"] else "")
                           for e in s["steps"])] for s in data["signals"]],
               [14, 50, 18, 20, 12, 10, 22, 14, 6, 20, 50, 70])
    xlsx_sheet(wb, "Not relevant",
               ["Section", "Day", "Title", "Link", "Decision", "Decided by", "Decided (Cairo)", "Reason"],
               [[r["section"], r["day"], r["title"], r.get("link") or r.get("pubmed") or "", *_decision_cells(r)]
                for r in data["not_relevant"]],
               [22, 16, 64, 46, 20, 20, 18, 44], links=True)
    _annex_sheet(wb, "Screening annex", data["annex"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_inspection_xlsx(data: dict) -> bytes:
    import io

    wb = xlsx_workbook(f"{data['title']}, {data['period'].label}")
    xlsx_summary(wb.active, data["summary"])
    xlsx_sheet(wb, "Coverage", ["Country", "Her page", "Kind", "Address", "Read by the app", "Sources", "Note"],
               [[c["country"], c["label"], c["kind"], c["url"] or "", c["status"], c["read_by"], c["note"]]
                for c in data["coverage"]],
               [18, 36, 20, 50, 34, 30, 50], links=True)
    _annex_sheet(wb, "Screening log", data["annex"])
    xlsx_sheet(wb, "Decisions", ["When (Cairo)", "Notice (original title)", "Decision", "Before", "By", "Reason"],
               [[d["at"], d["title"], d["decision"], d["before"], d["person"], d["reason"]] for d in data["decisions"]],
               [18, 60, 22, 22, 22, 50])
    xlsx_sheet(wb, "Signatures", ["When (Cairo)", "Record", "Meaning", "Signed by", "Role", "Comment", "SHA-256 signed",
                                  "Now"],
               [[s["at"], s["record"], s["meaning"], s["name"], s["role"], s["comment"], s["sha"], s["state"]]
                for s in data["signatures"]],
               [18, 40, 12, 22, 14, 40, 68, 26])
    xlsx_sheet(wb, "Authority reports", ["Sent on", "Notice", "Authority", "Reference", "By", "Note", "Withdrawn"],
               [[s["on"], s["title"], s["authority"], s["reference"], s["person"], s["note"], s["withdrawn"]]
                for s in data["sent"]],
               [14, 60, 10, 22, 22, 40, 50])
    xlsx_sheet(wb, "Weekly reports", ["Week", "Made (Cairo)", "PDF SHA-256", "Excel SHA-256", "Code", "Made by run",
                                      "Signatures"],
               [[w["week"], w["made"], w["pdf_sha256"], w["xlsx_sha256"], w["git_sha"], w["run"], w["signed"]]
                for w in data["weekly"]],
               [28, 18, 68, 68, 14, 50, 70], links=True)
    xlsx_sheet(wb, "Archive checks", ["Checked (Cairo)", "Files sampled", "Not matching", "Missing", "Result", "Code"],
               [[c["at"], c["sampled"], c["mismatched"], c["missing"], c["result"], c["git_sha"]]
                for c in data["checks"]],
               [18, 12, 12, 10, 36, 14])
    xlsx_sheet(wb, "Audit log", ["Table", "Change", "Rows"],
               [[a["table"], a["action"], a["n"]] for a in data["audit"]], [28, 12, 10])
    xlsx_sheet(wb, "People and roles", ["Name", "Role", "State", "Telegram", "Added"],
               [[p["name"], p["role"], p["active"], p["telegram"], p["added"]] for p in data["people"]],
               [30, 16, 14, 10, 14])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ───────────────────────────── PDF ─────────────────────────────

def render_pack_html(data: dict) -> str:
    env = _env()
    env.filters["language"] = rw.language
    return env.get_template(f"{data['kind']}.html").render(
        data=data, period=data["period"], title=data["title"], page=PAGE, hers=HERS, others=OTHERS,
        logo_src=logo_data_uri(), sato_src=logo_data_uri(SATO_LOGO), credit=CREDIT, copyright=copyright_line())


# ───────────────────────────── made, stored, told ─────────────────────────────

def _slug(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-") or "pack"


def file_stem(req: dict, ingredient: str | None = None) -> str:
    """"PHAROS-PSUR-levofloxacin-2024-12-02-to-2026-11-06" / "PHAROS-inspection-2025-11-07-to-2026-11-06"."""
    days = f"{as_day(req['from_day']).isoformat()}-to-{as_day(req['to_day']).isoformat()}"
    if req["kind"] == "psur":
        return f"PHAROS-PSUR-{_slug(ingredient or 'ingredient')}-{days}"
    return f"PHAROS-inspection-{days}"


def make_pack(db: Any, req: dict, *, archive: Any, check: Callable[[], None] = _no_check,
              made_at: datetime | None = None) -> dict:
    """Builds, prints and archives one pack. Returns the keys and SHA-256 of both files, and the PDF."""
    if req["kind"] == "psur":
        data = assemble_psur(gather_psur(db, req, check), made_at)
        xlsx = build_psur_xlsx(data)
        stem = file_stem(req, data["ingredient"]["name"])
    elif req["kind"] == "inspection":
        data = assemble_inspection(gather_inspection(db, req, check), made_at)
        xlsx = build_inspection_xlsx(data)
        stem = file_stem(req)
    else:
        raise ValueError(f"unknown pack {req['kind']!r}")
    check()
    pdf = build_pdf(render_pack_html(data), render_footer(data["period"]))
    base = f"reports/packs/{req['kind']}/{req['id']}/{stem}"
    # A pack made again never overwrites (bucket lock): it is stored as -r2, -r3 …
    xlsx_sha, xlsx_key = archive.put_named(f"{base}.xlsx", xlsx, XLSX_MIME, revise=True)
    pdf_sha, pdf_key = archive.put_named(f"{base}.pdf", pdf, "application/pdf", revise=True)
    return {"pdf_r2_key": pdf_key, "pdf_sha256": pdf_sha, "xlsx_r2_key": xlsx_key, "xlsx_sha256": xlsx_sha,
            "pdf": pdf, "filename": f"{stem}.pdf", "what": pack_name(req, data)}


def pack_name(req: dict, data: dict | None = None) -> str:
    """"PSUR pack, levofloxacin, 2 Dec 2024 – 6 Nov 2026"."""
    days = days_label(as_day(req["from_day"]), as_day(req["to_day"]))
    ing = ((data or {}).get("ingredient") or {}).get("name") or req.get("ingredient_name")
    return ", ".join(x for x in (NAME.get(req["kind"], "Pack"), ing if req["kind"] == "psur" else None, days) if x)


def _people_to_tell(store: Any, req: dict) -> list[dict]:
    """The person who asked (a reviewer or an administrator with Telegram), then every administrator. An
    inspection pack is for administrators only: a reviewer who asked for one before that is not told."""
    out: dict[str, dict] = {}
    for p in store.reminder_people() if req.get("kind") != "inspection" else ():
        if str(p["person_id"]) == str(req.get("requested_by")):
            out[str(p["person_id"])] = p
    for p in store.admins():
        out.setdefault(str(p["person_id"]), p)
    return list(out.values())


def _tell(notifier: Any, store: Any, req: dict, text: str, document: dict | None = None) -> int:
    people = _people_to_tell(store, req)
    for person in people:
        notifier._deliver(person, None, "report", text, document)
    return len(people)


def ready_message(what: str, req: dict) -> str:
    from collectors.alerts import BRAND, esc

    lines = [f"<b>{BRAND}</b> · pack ready", f"<b>{esc(what)}</b>"]
    if req.get("requested_by_name"):
        lines.append(f"Asked for by {esc(req['requested_by_name'])}")
    lines += ["", f"The PDF and the Excel file are on Reports: {REPORTS_URL}"]
    return "\n".join(lines)


def failed_message(what: str, req: dict, why: str) -> str:
    from collectors.alerts import BRAND, esc, esc_cut

    return "\n".join([f"<b>{BRAND}</b> · pack not made", f"<b>{esc(what)}</b>",
                      f"It could not be made: {esc_cut(why, 600)}", "", f"Ask for it again on Reports: {REPORTS_URL}"])


def fulfil_requests(db: Any, store: Any, *, dry_run: bool = False, archive: Any = None, notifier: Any = None,
                    clock: Callable[[], float] = time.monotonic, budget_s: float = BUDGET_S) -> dict | None:
    """Builds the oldest waiting request, if there is one, and tells the person who asked. Never raises: a
    failure is recorded on the request. Returns what happened, or None when nothing waited."""
    from collectors.alerts import esc_cut
    from collectors.core.context import redact

    try:
        req = store.claim_report_request()
    except Exception:  # noqa: BLE001 - the packs never fail the run
        log.warning("packs: the waiting requests could not be read: %s", redact(traceback.format_exc()))
        return None
    if not req:
        return None
    what = pack_name(req)
    try:
        if archive is None:
            from collectors.core.archive import Archive

            archive = Archive()
        if notifier is None:
            from collectors.alerts import Notifier

            notifier = Notifier(store, store.settings(), dry_run=dry_run, archive=archive)
        if int(req.get("attempts") or 0) > MAX_ATTEMPTS:
            why = (f"It was stopped before it was finished {MAX_ATTEMPTS} times. "
                   "Ask for fewer days, or tell the administrator.")
            store.fail_report_request(req["id"], why)
            _tell(notifier, store, req, failed_message(what, req, why))
            return {"id": req["id"], "status": "failed", "error": why}
        budget = Budget(clock, budget_s)
        try:
            out = make_pack(db, req, archive=archive, check=budget.check)
        except OutOfTime:
            minutes = round(budget_s / 60)
            if int(req.get("attempts") or 0) >= MAX_ATTEMPTS:
                why = (f"It took longer than {minutes} minutes {MAX_ATTEMPTS} times. "
                       "Ask for fewer days, or tell the administrator.")
                store.fail_report_request(req["id"], why)
                _tell(notifier, store, req, failed_message(what, req, why))
                return {"id": req["id"], "status": "failed", "error": why}
            note = f"Took longer than {minutes} minutes; the next collection run goes on with it."
            store.requeue_report_request(req["id"], note)
            log.warning("packs: %s: %s", req["id"], note)
            return {"id": req["id"], "status": "queued", "error": note}
        except Exception as exc:  # noqa: BLE001 - a pack that cannot be made is recorded, never raised
            why = redact(f"{type(exc).__name__}: {exc}")[:1000]
            log.warning("packs: %s failed: %s", req["id"], redact(traceback.format_exc()))
            store.fail_report_request(req["id"], why)
            _tell(notifier, store, req, failed_message(what, req, why))
            return {"id": req["id"], "status": "failed", "error": why}
        store.finish_report_request(
            req["id"], pdf_r2_key=out["pdf_r2_key"], pdf_sha256=out["pdf_sha256"], xlsx_r2_key=out["xlsx_r2_key"],
            xlsx_sha256=out["xlsx_sha256"], git_sha=os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA"),
            made_by_run=rw.run_address())
        document = ({"filename": out["filename"], "content": out["pdf"], "caption": esc_cut(out["what"], 1000)}
                    if len(out["pdf"]) <= MAX_DOCUMENT_BYTES else None)
        _tell(notifier, store, req, ready_message(out["what"], req), document)
        return {"id": req["id"], "status": "done", "pdf_sha256": out["pdf_sha256"],
                "xlsx_sha256": out["xlsx_sha256"], "pdf_r2_key": out["pdf_r2_key"]}
    except Exception:  # noqa: BLE001 - recording the outcome failed; the request is retried once it is stale
        log.warning("packs: %s could not be recorded: %s", req.get("id"), redact(traceback.format_exc()))
        return {"id": req.get("id"), "status": "unknown"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.report_pack", description=__doc__.split("\n\n")[0])
    ap.add_argument("--waiting", action="store_true", help="print how many requests wait, and stop")
    ap.add_argument("--dry-run", action="store_true", help="never send a real Telegram message")
    args = ap.parse_args(argv)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from collectors.core.context import install_log_redaction

    install_log_redaction()
    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    store = Store(db)
    if args.waiting:
        print(store.report_requests_waiting())
        return 0
    result = fulfil_requests(db, store, dry_run=args.dry_run)
    print(result if result is not None else "No pack is waiting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
