"""PDF text extraction: ``pdftotext -layout``, with tesseract OCR for pages under 25 words.

Line-end hyphenation is left in place here; matching rejoins it (collectors/matching.py).
Needs poppler-utils (pdftotext, pdftoppm) and tesseract with the language packs below on the runner.
"""

from __future__ import annotations

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


def extract_text(content: bytes, lang_hint: str | None) -> tuple[str, str, int]:
    """-> (text, method 'text'|'ocr'|'none', words). Pages are joined with form feeds."""
    if not content or not content.lstrip()[:5].startswith(b"%PDF"):
        return "", "none", 0
    with tempfile.TemporaryDirectory(prefix="pdf-") as tmp:
        workdir = Path(tmp)
        pdf = workdir / "in.pdf"
        pdf.write_bytes(content)
        try:
            pages = _pdftotext_pages(pdf)
        except subprocess.TimeoutExpired:
            pages = None
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
        return "", "none", 0
    return text, ("ocr" if used_ocr else "text"), words
