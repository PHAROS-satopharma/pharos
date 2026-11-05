"""The monthly report files carry Sato Pharma's credit: logo, credit line and copyright, in both files."""
import io
import shutil
import subprocess
from datetime import date, datetime, timezone

import pytest

from openpyxl import load_workbook

from collectors import report
from collectors.report import CREDIT, Month, build_xlsx, copyright_line, render_footer, render_html

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


def test_pdf_html_closes_with_the_credit():
    html = render_html(DATA, MONTH)
    sato = report.logo_data_uri(report.SATO_LOGO)
    assert html.count(sato) == 1          # the closing credit; the running foot is footer.html
    assert CREDIT in html
    assert html.count(copyright_line()) == 1
    assert "<footer" not in html          # a position: fixed footer printed on the last page only


def test_running_footer_carries_the_logo_copyright_and_page_number():
    foot = render_footer(MONTH)
    assert report.logo_data_uri(report.SATO_LOGO) in foot
    assert copyright_line() in foot
    assert 'class="pageNumber"' in foot and 'class="totalPages"' in foot
    assert "October 2026" in foot


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(shutil.which("pdftotext") is None or not _chromium_ready(),
                    reason="needs Chromium (playwright install chromium) and poppler's pdftotext")
def test_every_pdf_page_prints_the_footer():
    many = dict(DATA, sources=[dict(DATA["sources"][0], id=f"source-{k}") for k in range(90)])
    pdf = report.build_pdf(render_html(many, MONTH), render_footer(MONTH))
    pages = subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True,
                           check=True).stdout.decode("utf-8").split("\f")
    pages = [p for p in pages if p.strip()]
    assert len(pages) >= 3
    for n, text in enumerate(pages, start=1):
        flat = " ".join(text.split())          # pdftotext -layout pads the footer's spans with spaces
        foot = flat[-200:]
        assert "Sato Pharma. All rights reserved." in flat, f"page {n} has no footer: …{foot}"
        assert f"Page {n} of {len(pages)}" in flat, f"page {n} has no page number: …{foot}"


def test_copyright_year_is_the_cairo_year():
    assert copyright_line() == f"© {datetime.now(report.CAIRO).year} Sato Pharma. All rights reserved."
