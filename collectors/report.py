"""PHAROS monthly screening report for the previous month (Cairo calendar).

    python -m collectors.report [--month YYYY-MM] [--dry-run]

Builds ``PHAROS-screening-YYYY-MM.xlsx`` (sheets: Summary, Sources screened, Issues found, Review log)
and ``PHAROS-screening-YYYY-MM.pdf`` (report_templates/monthly.html printed by Playwright, A4),
archives both, records them in ``monthly_report`` with their hashes, and sends the PDF to the admins
on Telegram (dry-run aware). Times are shown in Cairo local time.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger("collectors.report")

CAIRO = ZoneInfo("Africa/Cairo")
TEMPLATES = Path(__file__).resolve().parent / "report_templates"
# The owner's final logos, used as supplied: stacked (1536×1024) for cover/title positions, wide
# (2000×667) for one-line running headers. The monthly report has no cover and no running header,
# so page 1 opens with the stacked logo and no other logo appears.
LOGO_STACKED = TEMPLATES / "pharos-logo-stacked.png"
LOGO_WIDE = TEMPLATES / "pharos-logo.png"
LOGO = LOGO_STACKED
TITLE = "PHAROS — Monthly screening report"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
STATUS_LABEL = {"new": "New", "reviewed": "Reviewed", "relevant": "Relevant",
                "not_relevant": "Not relevant"}
HEALTH_LABEL = {"unknown": "Not yet run", "ok": "OK", "degraded": "Needs attention",
                "down": "Down", "blocked": "Blocked"}


@dataclass
class Month:
    first: date

    @property
    def label(self) -> str:
        return f"{self.first:%B %Y}"

    @property
    def slug(self) -> str:
        return f"{self.first:%Y-%m}"

    @property
    def next_first(self) -> date:
        y, m = self.first.year + (self.first.month == 12), self.first.month % 12 + 1
        return date(y, m, 1)

    def bounds_utc(self) -> tuple[datetime, datetime]:
        a = datetime.combine(self.first, time(0), CAIRO).astimezone(timezone.utc)
        b = datetime.combine(self.next_first, time(0), CAIRO).astimezone(timezone.utc)
        return a, b


def previous_month(today: date | None = None) -> Month:
    today = today or datetime.now(CAIRO).date()
    y, m = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return Month(date(y, m, 1))


def cairo(ts: datetime | None) -> str:
    return ts.astimezone(CAIRO).strftime("%d %b %Y %H:%M") if ts else ""


# ───────────────────────────── data ─────────────────────────────

def gather(db: Any, month: Month) -> dict:
    start, end = month.bounds_utc()
    p = {"a": start, "b": end}
    sources = db.fetchall(
        """select s.id, s.kind::text as kind, s.channel::text as channel, s.health::text as health,
                  s.enabled, r.country_name, r.name as regulator,
                  count(sr.id) as runs,
                  count(sr.id) filter (where sr.error is null or sr.error = 'imap not configured') as successes,
                  count(sr.id) filter (where sr.error is not null and sr.error <> 'imap not configured') as failures,
                  coalesce(sum(sr.items_seen), 0) as items_seen,
                  coalesce(sum(sr.items_new), 0) as items_new,
                  coalesce(sum(sr.items_matched), 0) as items_matched,
                  max(sr.started_at) as last_run
             from source s
             join regulator r on r.id = s.regulator_id
             left join source_run sr on sr.source_id = s.id
                  and sr.started_at >= %(a)s and sr.started_at < %(b)s
            where s.enabled or exists (select 1 from source_run x where x.source_id = s.id
                                        and x.started_at >= %(a)s and x.started_at < %(b)s)
            group by s.id, r.country_name, r.name
            order by r.country_name, s.id""", p)
    issues = db.fetchall(
        """select v.id, v.first_date, v.doc_type::text as doc_type, v.title, v.status::text as status,
                  v.class_only, v.is_backfill, v.link, v.countries, v.ingredients, v.copies,
                  i.created_at,
                  (select json_build_object('to', re.to_status::text, 'comment', re.comment,
                          'person', p.full_name, 'at', re.created_at)
                     from review_event re join person p on p.id = re.person_id
                    where re.issue_id = v.id order by re.created_at desc limit 1) as decision
             from v_issue_table v join issue i on i.id = v.id
            where i.created_at >= %(a)s and i.created_at < %(b)s
            order by v.first_date nulls last, i.created_at""", p)
    reviews = db.fetchall(
        """select re.created_at, re.from_status::text as from_status, re.to_status::text as to_status,
                  re.comment, p.full_name as person, i.title
             from review_event re join person p on p.id = re.person_id
             join issue i on i.id = re.issue_id
            where re.created_at >= %(a)s and re.created_at < %(b)s
            order by re.created_at""", p)
    runs = db.fetchone(
        """select count(*) as runs, count(*) filter (where ok) as ok_runs
             from run where started_at >= %(a)s and started_at < %(b)s""", p) or {}
    return {"sources": sources, "issues": issues, "reviews": reviews, "runs": runs}


def summary_rows(data: dict, month: Month) -> list[tuple[str, Any]]:
    s, i = data["sources"], data["issues"]
    return [
        ("Report", TITLE),
        ("Month", month.label),
        ("Generated (Cairo)", cairo(datetime.now(timezone.utc))),
        ("Collector runs", data["runs"].get("runs", 0)),
        ("Runs completed without error", data["runs"].get("ok_runs", 0)),
        ("Sources screened", sum(1 for r in s if r["runs"])),
        ("Sources with failures", sum(1 for r in s if r["failures"])),
        ("Notices read", sum(int(r["items_seen"]) for r in s)),
        ("New notices stored", sum(int(r["items_new"]) for r in s)),
        ("Notices matching the watchlist", sum(int(r["items_matched"]) for r in s)),
        ("Issues found", sum(1 for r in i if not r["is_backfill"])),
        ("Issues from the backfill", sum(1 for r in i if r["is_backfill"])),
        ("Review decisions", len(data["reviews"])),
    ]


# ───────────────────────────── XLSX ─────────────────────────────

def build_xlsx(data: dict, month: Month) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    # Navy of the logo; the wide logo heads the Summary sheet (openpyxl images need Pillow).
    ink, rule = "02224C", "D9D5CC"
    head_font = Font(name="IBM Plex Sans", bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1F4E5F")
    thin = Border(bottom=Side(style="thin", color=rule))
    body_font = Font(name="IBM Plex Sans", color=ink)

    wb = Workbook()

    def sheet(title: str, header: list[str], rows: list[list[Any]], widths: list[int]):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill, c.alignment = head_font, head_fill, Alignment(vertical="center")
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.font, c.border = body_font, thin
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for k, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(k)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        return ws

    ws = wb.active
    ws.title = "Summary"
    first = 1
    if LOGO_WIDE.exists():
        from openpyxl.drawing.image import Image as XLImage

        logo = XLImage(str(LOGO_WIDE))
        logo.height = 66  # px; the width keeps the logo's own 2000:667 shape
        logo.width = round(66 * 2000 / 667)
        ws.add_image(logo, "A1")
        ws.row_dimensions[1].height = 54
        ws.append([])
        ws.append([])
        first = 3
    for k, v in summary_rows(data, month):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 48
    ws[f"A{first}"].font = Font(name="IBM Plex Sans", bold=True, size=13, color=ink)
    ws[f"B{first}"].font = Font(name="IBM Plex Sans", bold=True, size=13, color=ink)

    sheet("Sources screened",
          ["Country", "Regulator", "Source", "Kind", "Channel", "Runs", "Successes", "Failures",
           "Items seen", "Items new", "Items matched", "Health now", "Last run (Cairo)"],
          [[r["country_name"], r["regulator"], r["id"], r["kind"], r["channel"], r["runs"],
            r["successes"], r["failures"], r["items_seen"], r["items_new"], r["items_matched"],
            HEALTH_LABEL.get(r["health"], r["health"]), cairo(r["last_run"])] for r in data["sources"]],
          [16, 34, 20, 10, 10, 7, 10, 9, 10, 10, 12, 16, 18])
    sheet("Issues found",
          ["Date", "Title (original)", "Countries", "Ingredients", "Type", "Class-wide", "Backfill",
           "Status", "Decision", "Reviewer", "Decision date (Cairo)", "Link"],
          [[r["first_date"], r["title"], ", ".join(r["countries"] or []),
            ", ".join(r["ingredients"] or []), r["doc_type"], "yes" if r["class_only"] else "",
            "yes" if r["is_backfill"] else "", STATUS_LABEL.get(r["status"], r["status"]),
            (r["decision"] or {}).get("comment") or "", (r["decision"] or {}).get("person") or "",
            _decision_at(r), r["link"]] for r in data["issues"]],
          [12, 60, 24, 18, 12, 10, 9, 13, 40, 20, 18, 50])
    sheet("Review log",
          ["When (Cairo)", "Issue", "From", "To", "Reviewer", "Comment"],
          [[cairo(r["created_at"]), r["title"], STATUS_LABEL.get(r["from_status"]),
            STATUS_LABEL.get(r["to_status"]), r["person"], r["comment"] or ""] for r in data["reviews"]],
          [18, 60, 12, 13, 20, 50])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _decision_at(row: dict) -> str:
    at = (row.get("decision") or {}).get("at")
    if isinstance(at, str):
        try:
            at = datetime.fromisoformat(at)
        except ValueError:
            return at
    return cairo(at) if at else ""


# ───────────────────────────── PDF ─────────────────────────────

def render_html(data: dict, month: Month) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html"]))
    env.filters["cairo"] = cairo
    env.filters["status"] = lambda s: STATUS_LABEL.get(s, s)
    env.filters["health"] = lambda s: HEALTH_LABEL.get(s, s)
    return env.get_template("monthly.html").render(
        title=TITLE, month=month, summary=summary_rows(data, month), sources=data["sources"],
        issues=data["issues"], reviews=data["reviews"], logo_src=logo_data_uri(),
        generated=cairo(datetime.now(timezone.utc)))


def logo_data_uri(path: Path = LOGO) -> str:
    """A logo embedded in the HTML, so set_content() needs no file access and the PDF carries it."""
    import base64

    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_pdf(html: str) -> bytes:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            return page.pdf(format="A4", print_background=True, prefer_css_page_size=True,
                            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        finally:
            browser.close()


# ───────────────────────────── main ─────────────────────────────

def make_report(db: Any, store: Any, month: Month, *, dry_run: bool = False) -> dict:
    from collectors.alerts import Notifier
    from collectors.core.archive import Archive

    data = gather(db, month)
    xlsx = build_xlsx(data, month)
    pdf = build_pdf(render_html(data, month))
    archive = Archive()
    base = f"reports/{month.slug}/PHAROS-screening-{month.slug}"
    # A re-run for the same month never overwrites (bucket lock): it is stored as -r2, -r3 …
    xlsx_sha, xlsx_key = archive.put_named(f"{base}.xlsx", xlsx, XLSX_MIME, revise=True)
    pdf_sha, pdf_key = archive.put_named(f"{base}.pdf", pdf, "application/pdf", revise=True)
    db.execute(
        """insert into monthly_report (month, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256)
           values (%(m)s, %(xk)s, %(xs)s, %(pk)s, %(ps)s)
           on conflict (month) do update set xlsx_r2_key = excluded.xlsx_r2_key,
             xlsx_sha256 = excluded.xlsx_sha256, pdf_r2_key = excluded.pdf_r2_key,
             pdf_sha256 = excluded.pdf_sha256, generated_at = now()""",
        {"m": month.first, "xk": xlsx_key, "xs": xlsx_sha, "pk": pdf_key, "ps": pdf_sha})
    out_dir = Path(os.environ.get("REPORT_DIR", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"PHAROS-screening-{month.slug}.xlsx").write_bytes(xlsx)
    (out_dir / f"PHAROS-screening-{month.slug}.pdf").write_bytes(pdf)
    notifier = Notifier(store, store.settings(), dry_run=dry_run, archive=archive)
    notifier.admin_document(f"PHAROS-screening-{month.slug}.pdf", pdf,
                            f"{TITLE}, {month.label}")
    return {"month": month.slug, "xlsx_sha256": xlsx_sha, "pdf_sha256": pdf_sha}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.report")
    ap.add_argument("--month", help="YYYY-MM (default: the previous month, Cairo calendar)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level="INFO")
    from collectors.core.db import Db
    from collectors.core.store import Store

    month = Month(date.fromisoformat(args.month + "-01")) if args.month else previous_month()
    db = Db()
    result = make_report(db, Store(db), month, dry_run=args.dry_run)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
