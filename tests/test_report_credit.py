"""The monthly report files carry Sato Pharma's credit: logo, credit line and copyright, in both files."""
import io
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timezone

import pytest

from openpyxl import load_workbook

from collectors import report
from collectors.report import CREDIT, Month, build_xlsx, copyright_line, render_footer, render_html

MONTH = Month(date(2026, 10, 1))
SEPTEMBER = Month(date(2026, 9, 1))   # the longest month name, for the footer line
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
    assert "<span>by Sato Pharma</span>" not in html   # the old plain-text credit


def test_running_footer_carries_the_logo_copyright_and_page_number():
    foot = render_footer(MONTH)
    assert report.logo_data_uri(report.SATO_LOGO) in foot
    assert copyright_line() in foot
    assert 'class="pageNumber"' in foot and 'class="totalPages"' in foot
    assert "October 2026" in foot
    assert "<span>by Sato Pharma</span>" not in foot


def _poppler() -> bool:
    exe = shutil.which("pdftotext")
    if not exe:
        return False
    proc = subprocess.run([exe, "-v"], capture_output=True, check=False)
    return b"poppler" in (proc.stdout + proc.stderr).lower()


def _unavailable(reason: str):
    # CI sets REPORT_PDF=true when the report changed: there a missing tool fails the test, it never skips.
    if os.environ.get("REPORT_PDF") == "true":
        pytest.fail(reason)
    pytest.skip(reason)


def test_every_pdf_page_prints_the_footer(tmp_path):
    if not _poppler():
        _unavailable("needs poppler's pdftotext and pdfimages")
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        _unavailable("needs Playwright (pip install -r collectors/requirements.txt)")
    # More than ten pages, so the footer is read with two-digit page numbers and the longest month name.
    many = dict(DATA, sources=[dict(DATA["sources"][0], id=f"source-{k}") for k in range(400)])
    # No web fonts: the test never waits on fonts.googleapis.com (the footer uses system fonts anyway).
    html = re.sub(r"<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>", "", render_html(many, SEPTEMBER))
    try:
        pdf = report.build_pdf(html, render_footer(SEPTEMBER))
    except PlaywrightError as e:
        _unavailable(f"needs Chromium (python -m playwright install chromium): {e}")
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf)
    text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True,
                          check=True).stdout.decode("utf-8")
    pages = [p for p in text.split("\f") if p.strip()]
    total = len(pages)
    assert total >= 10
    for n, page_text in enumerate(pages, start=1):
        # The footer is the last line of the page; pdftotext -layout pads its spans with spaces.
        foot = " ".join(page_text.strip().splitlines()[-1].split())
        assert foot.startswith("PHAROS · Monthly screening report · September 2026"), f"page {n}: {foot}"
        assert copyright_line() in foot, f"page {n} has no footer credit: {foot}"
        assert foot.endswith(f"Page {n} of {total}"), f"page {n} has no page number: {foot}"
    # The footer's Sato Pharma logo is an image on every page (pdftotext cannot see it).
    listing = subprocess.run(["pdfimages", "-list", str(path)], capture_output=True,
                             check=True).stdout.decode("utf-8")
    with_image = {int(line.split()[0]) for line in listing.splitlines()[2:] if line.strip()}
    assert with_image == set(range(1, total + 1))


def test_copyright_year_is_the_cairo_year():
    assert copyright_line() == f"© {datetime.now(report.CAIRO).year} Sato Pharma. All rights reserved."
