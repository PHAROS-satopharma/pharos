"""The monthly report files carry Sato Pharma's credit: logo, credit line and copyright, in both files."""
import io
from datetime import date, datetime, timezone

from openpyxl import load_workbook

from collectors import report
from collectors.report import CREDIT, Month, build_xlsx, copyright_line, render_html

MONTH = Month(date(2026, 10, 1))
DATA = {
    "sources": [{
        "id": "basg-safety", "kind": "safety", "channel": "web", "health": "ok", "enabled": True,
        "country_name": "Austria", "regulator": "BASG", "runs": 60, "successes": 60, "failures": 0,
        "items_seen": 2040, "items_new": 4, "items_matched": 1,
        "last_run": datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc),
    }],
    "issues": [],
    "reviews": [],
    "runs": {"runs": 60, "ok_runs": 60},
}


def test_xlsx_summary_closes_with_the_credit_and_every_sheet_prints_it():
    wb = load_workbook(io.BytesIO(build_xlsx(DATA, MONTH)))
    summary = wb["Summary"]
    texts = [c.value for row in summary.iter_rows() for c in row if isinstance(c.value, str)]
    assert CREDIT in texts
    assert copyright_line() in texts
    # the PHAROS logo heads the sheet and the Sato Pharma logo sits at the foot
    assert len(summary._images) == 2
    for ws in wb.worksheets:
        assert "Sato Pharma" in (ws.oddFooter.left.text or ""), ws.title
    assert wb.properties.creator == "Sato Pharma"


def test_pdf_html_carries_the_logo_credit_and_copyright():
    html = render_html(DATA, MONTH)
    sato = report.logo_data_uri(report.SATO_LOGO)
    assert html.count(sato) == 2          # the running footer and the closing credit
    assert CREDIT in html
    assert html.count(copyright_line()) == 2
    assert "<span>by Sato Pharma</span>" not in html   # the old plain-text credit


def test_copyright_year_is_the_cairo_year():
    assert copyright_line() == f"© {datetime.now(report.CAIRO).year} Sato Pharma. All rights reserved."
