"""Helpers every parser may use: dates, URLs, HTML text and attachment links, keyword filters.

Re-exports the contract types so a parser needs one import:
``from collectors.parsers.base import Item, SourceConfig, ParseError, SourceBlocked``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from collectors.core.context import FetchContext, FetchError, ParseError, SourceBlocked
from collectors.core.models import Fetched, Item, SourceConfig

__all__ = ["FetchContext", "FetchError", "Fetched", "Item", "ParseError", "SourceBlocked",
           "SourceConfig", "absolute", "attachment_links", "html_text", "keyword_ok", "parse_date",
           "soup"]

_DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_YMD = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})\b")
_YMD_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_JA = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_KO = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def parse_date(value: str | date | datetime | None, *, dayfirst: bool = True) -> date | None:
    """Best-effort date from the formats regulators use (RFC 822, ISO, d/m/Y, 年月日, 년월일)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for rx in (_JA, _KO):
        m = rx.search(s)
        if m:
            return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _YMD_COMPACT.match(s)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _YMD.search(s)
    if m:
        return _safe(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _DMY.search(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _safe(y, b, a) if dayfirst else _safe(y, a, b)
    try:
        return parsedate_to_datetime(s).date()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        from dateutil import parser as du

        return du.parse(s, dayfirst=dayfirst, fuzzy=True).date()
    except (ValueError, OverflowError, ImportError):
        return None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def absolute(href: str, base: str) -> str:
    """Absolute URL without the fragment."""
    url = urljoin(base, href.strip())
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def soup(fetched_or_html: Fetched | str):
    from bs4 import BeautifulSoup

    html = fetched_or_html.text if isinstance(fetched_or_html, Fetched) else fetched_or_html
    return BeautifulSoup(html, "lxml")


_BOILERPLATE = ("script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe",
                "template", "aside")


def html_text(html_or_soup, selector: str | None = None) -> str:
    """Readable text of the main content: ``selector`` if given, else main/article/#content/body."""
    doc = soup(html_or_soup) if isinstance(html_or_soup, (str, Fetched)) else html_or_soup
    node = None
    if selector:
        node = doc.select_one(selector)
    if node is None:
        for sel in ("main", "article", "[role=main]", "#content", "#main-content", ".content", "body"):
            node = doc.select_one(sel)
            if node is not None:
                break
    if node is None:
        node = doc
    for tag in node.find_all(_BOILERPLATE):
        tag.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    text = node.get_text("\n")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if ln:
            out.append(ln)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


_ATTACHMENT_HINTS = (".pdf", "blob=publicationfile", "/media/", "/documents/", "download",
                     "/files/", "/file/", ".hwp", ".docx")


def attachment_links(html_or_soup, base_url: str, *, selector: str | None = None,
                     patterns: Iterable[str] | None = None) -> list[str]:
    """Links to PDFs (and other originals) in the page or in ``selector``; deduplicated, in order."""
    doc = soup(html_or_soup) if isinstance(html_or_soup, (str, Fetched)) else html_or_soup
    scope = doc.select_one(selector) if selector else None
    scope = scope or doc
    hints = tuple(p.lower() for p in (patterns or _ATTACHMENT_HINTS))
    out: list[str] = []
    for a in scope.select("a[href]"):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        low = href.lower()
        ok = any(h in low for h in hints) if patterns else (
            low.split("?")[0].endswith(".pdf") or "blob=publicationfile" in low
            or (a.get("type") or "").lower() == "application/pdf")
        if ok:
            url = absolute(href, base_url)
            if url not in out:
                out.append(url)
    return out


def keyword_ok(text: str, include: Iterable[str] | None = None,
               exclude: Iterable[str] | None = None) -> bool:
    """Case-insensitive filter: any include keyword present (if given), no exclude keyword present."""
    low = (text or "").casefold()
    inc = [k.casefold() for k in (include or []) if k]
    exc = [k.casefold() for k in (exclude or []) if k]
    if inc and not any(k in low for k in inc):
        return False
    return not any(k in low for k in exc)
