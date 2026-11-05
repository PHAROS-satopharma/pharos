"""PDF text extraction: ``pdftotext -layout``, with tesseract OCR for pages under 25 words.

Line-end hyphenation is left in place here; matching rejoins it (collectors/matching.py).
Needs poppler-utils (pdftotext, pdftoppm) and tesseract with the language packs below on the runner.

Two-column pages (Japanese 添付文書): ``-layout`` reads straight across both columns, so a
right-column heading lands in the middle of a left-column line. ``extract_text_by_columns``
(opt-in; only the PMDA label watch uses it) reads the word boxes (``pdftotext -bbox``), finds the
gutter of each page and reads the left column top to bottom, then the right one; a line that
crosses the gutter (a centred title, a full-width table) is read in place between the column
bands. A page with no gutter keeps its ``-layout`` text unchanged.
"""

from __future__ import annotations

import html
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

MIN_WORDS_PER_PAGE = 25
MAX_OCR_PAGES = 40
PDFTOTEXT_TIMEOUT = 120
OCR_TIMEOUT = 180

TESSERACT_LANG = {
    "ja": "jpn", "ko": "kor", "fi": "fin", "sv": "swe", "da": "dan", "nb": "nor", "nn": "nor",
    "no": "nor", "is": "isl", "de": "deu", "fr": "fra", "it": "ita", "es": "spa", "pt": "por",
    "nl": "nld", "ar": "ara", "en": "eng",
}

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힣豈-﫿]")


def count_words(text: str) -> int:
    """Whitespace words, plus one word per two CJK/Hangul characters (they are not space-separated)."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    latin = len(_CJK.sub(" ", text).split())
    return latin + cjk // 2


def tesseract_lang(lang_hint: str | None) -> str:
    code = TESSERACT_LANG.get((lang_hint or "en").split("-")[0].lower(), "eng")
    return code if code == "eng" else f"{code}+eng"


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _pdftotext_pages(pdf: Path) -> list[str] | None:
    if not shutil.which("pdftotext"):
        return None
    proc = _run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"], PDFTOTEXT_TIMEOUT)
    if proc.returncode != 0:
        log.warning("pdftotext failed: %s", proc.stderr.decode("utf-8", "replace")[:300])
        return None
    text = proc.stdout.decode("utf-8", "replace")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def _page_count(pdf: Path) -> int:
    if not shutil.which("pdfinfo"):
        return 0
    proc = _run(["pdfinfo", str(pdf)], 60)
    m = re.search(rb"Pages:\s+(\d+)", proc.stdout)
    return int(m.group(1)) if m else 0


def _ocr_page(pdf: Path, page: int, lang: str, workdir: Path) -> str:
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    prefix = workdir / f"p{page}"
    proc = _run(["pdftoppm", "-r", "300", "-gray", "-f", str(page), "-l", str(page), "-png",
                 "-singlefile", str(pdf), str(prefix)], OCR_TIMEOUT)
    image = prefix.with_suffix(".png")
    if proc.returncode != 0 or not image.exists():
        return ""
    for attempt in (lang, "eng"):
        proc = _run(["tesseract", str(image), "-", "-l", attempt, "--psm", "3"], OCR_TIMEOUT)
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", "replace")
        log.warning("tesseract -l %s failed on page %s: %s", attempt, page,
                    proc.stderr.decode("utf-8", "replace")[:200])
    return ""


# ───────────────────────────── two-column pages ─────────────────────────────

Word = tuple[float, float, float, float, str]          # xMin, yMin, xMax, yMax, text

MIN_GUTTER = 6.0          # pt: the narrowest empty strip between two columns
MIN_SIDE_BY_SIDE = 5      # left-column lines with right-column text beside them, at least
GUTTER_SLACK = 2          # words allowed across the gutter strip (a page number, a centred title)
_PAGE = re.compile(r'<page width="([-\d.]+)" height="[-\d.]+">(.*?)</page>', re.S)
_WORD = re.compile(r'<word xMin="([-\d.]+)" yMin="([-\d.]+)" xMax="([-\d.]+)" yMax="([-\d.]+)">'
                   r'(.*?)</word>', re.S)


def _bbox_pages(pdf: Path) -> list[tuple[float, list[Word]]] | None:
    """``[(page width, words), …]`` from ``pdftotext -bbox`` (poppler); None when it cannot run."""
    if not shutil.which("pdftotext"):
        return None
    proc = _run(["pdftotext", "-bbox", "-enc", "UTF-8", str(pdf), "-"], PDFTOTEXT_TIMEOUT)
    if proc.returncode != 0:
        log.warning("pdftotext -bbox failed: %s", proc.stderr.decode("utf-8", "replace")[:300])
        return None
    out = []
    for page in _PAGE.finditer(proc.stdout.decode("utf-8", "replace")):
        words = [(float(a), float(b), float(c), float(d), html.unescape(t))
                 for a, b, c, d, t in _WORD.findall(page.group(2))]
        out.append((float(page.group(1)), [w for w in words if w[4].strip()]))
    return out or None


def _same_line(a: tuple[float, float], b: tuple[float, float]) -> bool:
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    return overlap >= 0.5 * min(a[1] - a[0], b[1] - b[0])


def _lines(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines (top to bottom), each line left to right."""
    lines: list[list[Word]] = []
    span: tuple[float, float] | None = None
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        if span is not None and _same_line(span, (w[1], w[3])):
            lines[-1].append(w)
            span = (min(span[0], w[1]), max(span[1], w[3]))
        else:
            lines.append([w])
            span = (w[1], w[3])
    return [sorted(line, key=lambda w: w[0]) for line in lines]


def _span(line: list[Word]) -> tuple[float, float]:
    return min(w[1] for w in line), max(w[3] for w in line)


def _gutter(words: list[Word], width: float) -> float | None:
    """The x of the gutter between two columns, or None for a page that is not two columns.

    The gutter is the middle of the widest strip (in the middle 40% of the page, at least
    ``MIN_GUTTER`` wide) crossed by at most ``GUTTER_SLACK`` more words than the least crossed x
    (so a centred page number does not hide it); the page is two columns only when at least
    ``MIN_SIDE_BY_SIDE`` left-column lines have right-column text beside them and those lines
    outnumber the lines crossing the strip at least two to one. One-column text crosses the middle
    on almost every line, so it never qualifies."""
    if not words or width <= 0:
        return None
    xs = range(int(width * 0.3), int(width * 0.7) + 1)
    counts = [sum(1 for w in words if w[0] < x < w[2]) for x in xs]
    if not counts:
        return None
    low = min(counts) + GUTTER_SLACK
    best: tuple[int, int] = (0, -1)          # (start, end) indices of the widest run under ``low``
    start = None
    for i, c in enumerate([*counts, low + 1]):
        if c <= low and start is None:
            start = i
        elif c > low and start is not None:
            if i - 1 - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    if best[1] < 0 or xs[best[1]] - xs[best[0]] < MIN_GUTTER:
        return None
    g = (xs[best[0]] + xs[best[1]]) / 2
    left = _lines([w for w in words if w[2] <= g])
    right = [_span(line) for line in _lines([w for w in words if w[0] >= g])]
    crossing = _lines([w for w in words if w[0] < g < w[2]])
    beside = sum(1 for line in left if any(_same_line(_span(line), r) for r in right))
    if beside < MIN_SIDE_BY_SIDE or beside < 2 * len(crossing):
        return None
    return g


def _render(lines: list[list[Word]]) -> list[str]:
    """Lines as text (words joined by one space), a blank line where the text skips a line."""
    out: list[str] = []
    prev: tuple[float, float] | None = None
    for line in lines:
        span = _span(line)
        if prev is not None and span[0] - prev[1] > 0.8 * (prev[1] - prev[0]):
            out.append("")
        out.append(" ".join(w[4] for w in line))
        prev = span
    return out


def _column_page(words: list[Word], g: float) -> str:
    """A two-column page read column by column: each band between full-width lines is read left
    column first, then right column; the full-width lines (a word crossing the gutter, or left and
    right text less than a line height apart, as in a centred title) stay in place."""
    rows = [_span(line) for line in _lines([w for w in words if w[0] < g < w[2]])]
    right_lines = _lines([w for w in words if w[0] >= g])
    for line in _lines([w for w in words if w[2] <= g]):
        span = _span(line)
        for r in right_lines:
            other = _span(r)
            if _same_line(span, other) and r[0][0] - line[-1][2] < span[1] - span[0]:
                rows.append((min(span[0], other[0]), max(span[1], other[1])))
    merged: list[list[float]] = []
    for top, bottom in sorted(rows):
        if merged and top <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], bottom)
        else:
            merged.append([top, bottom])
    # band i lies above full-width row i; band len(merged) is below the last one
    bands_l: list[list[Word]] = [[] for _ in range(len(merged) + 1)]
    bands_r: list[list[Word]] = [[] for _ in range(len(merged) + 1)]
    full: list[list[Word]] = [[] for _ in merged]
    for w in words:
        mid = (w[1] + w[3]) / 2
        inside = [i for i, (top, bottom) in enumerate(merged) if top <= mid <= bottom]
        if inside:                          # a word crossing the gutter is always inside its row
            full[inside[0]].append(w)
            continue
        band = sum(1 for top, _b in merged if top < mid)
        (bands_l if w[2] <= g else bands_r)[band].append(w)
    out: list[str] = []
    for i in range(len(merged) + 1):
        for part in (bands_l[i], bands_r[i]):
            if part:
                if out:
                    out.append("")
                out.extend(_render(_lines(part)))
        if i < len(merged) and full[i]:
            if out:
                out.append("")
            out.extend(_render(_lines(full[i])))
    return "\n".join(out)


def _column_pages(pdf: Path, layout: list[str]) -> list[str] | None:
    """``layout`` with every two-column page re-read column by column; None if the word boxes
    cannot be read or do not match the pages."""
    try:
        boxes = _bbox_pages(pdf)
    except subprocess.TimeoutExpired:
        return None
    if boxes is None or len(boxes) != len(layout):
        return None
    out = []
    for (width, words), page_text in zip(boxes, layout, strict=True):
        g = _gutter(words, width)
        out.append(page_text if g is None else _column_page(words, g))
    return out


# ───────────────────────────── extraction ─────────────────────────────

def extract_text(content: bytes, lang_hint: str | None) -> tuple[str, str, int]:
    """-> (text, method 'text'|'ocr'|'none', words). Pages are joined with form feeds."""
    text, method, words, _columns = _extract(content, lang_hint, columns=False)
    return text, method, words


def extract_text_by_columns(content: bytes, lang_hint: str | None) -> tuple[str, str, int, bool]:
    """``extract_text``, reading two-column pages column by column. The last value says whether
    the column reader ran (False: ``pdftotext -bbox`` was unavailable and the text is the plain
    ``-layout`` reading, exactly as ``extract_text`` gives it)."""
    return _extract(content, lang_hint, columns=True)


def _extract(content: bytes, lang_hint: str | None, *, columns: bool) -> tuple[str, str, int, bool]:
    if not content or not content.lstrip()[:5].startswith(b"%PDF"):
        return "", "none", 0, False
    by_columns = False
    with tempfile.TemporaryDirectory(prefix="pdf-") as tmp:
        workdir = Path(tmp)
        pdf = workdir / "in.pdf"
        pdf.write_bytes(content)
        try:
            pages = _pdftotext_pages(pdf)
        except subprocess.TimeoutExpired:
            pages = None
        if pages is not None and columns:
            read = _column_pages(pdf, pages)
            if read is not None:
                pages, by_columns = read, True
        if pages is None:
            pages = [""] * max(_page_count(pdf), 1)
        lang = tesseract_lang(lang_hint)
        used_ocr = False
        ocr_budget = MAX_OCR_PAGES
        out: list[str] = []
        for number, page_text in enumerate(pages, start=1):
            if count_words(page_text) < MIN_WORDS_PER_PAGE and ocr_budget > 0:
                ocr_budget -= 1
                try:
                    ocr = _ocr_page(pdf, number, lang, workdir)
                except subprocess.TimeoutExpired:
                    ocr = ""
                if count_words(ocr) > count_words(page_text):
                    page_text = ocr
                    used_ocr = True
            out.append(page_text)
    text = "\f".join(out).strip()
    words = count_words(text)
    if words == 0:
        return "", "none", 0, False
    return text, ("ocr" if used_ocr else "text"), words, by_columns
