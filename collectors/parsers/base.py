"""Helpers every parser may use: dates, URLs, HTML text and attachment links, keyword filters.

Re-exports the contract types so a parser needs one import:
``from collectors.parsers.base import Item, SourceConfig, ParseError, SourceBlocked``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit

from collectors.core.context import FetchContext, FetchError, NotSetUp, ParseError, SourceBlocked
from collectors.core.models import Fetched, Item, SourceConfig

__all__ = ["FetchContext", "FetchError", "Fetched", "Item", "NotSetUp", "ParseError", "SourceBlocked",
           "SourceConfig", "absolute", "attachment_links", "era_date", "html_text", "keyword_ok",
           "parse_date", "soup"]

_DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
# (?!\d) rather than \b after the day: an ISO timestamp ("2026-10-12T11:00") has no boundary before T
_YMD = re.compile(r"\b(\d{4})[./-](\d{1,2})[./-](\d{1,2})(?!\d)")
_YMD_COMPACT = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_JA = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_KO = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")

# Japanese era dates: 令和7年10月1日, 令和元年5月1日, 平成31年4月30日, 令和7年10月 (→ the 1st), and the
# short forms R7.10.1 / H31.4.30. 令和 1 = 2019, 平成 1 = 1989, 昭和 1 = 1926; 元 = year 1.
_ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925, "R": 2018, "H": 1988}
ERA_JA = re.compile(r"(令和|平成|昭和)\s*(元|\d{1,2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
_ERA_SHORT = re.compile(r"(?<![A-Za-z0-9])([RH])\s*(元|\d{1,2})[./](\d{1,2})[./](\d{1,2})(?![\d.])")


def era_date(text: str | None, *, short: bool = True) -> date | None:
    """A Japanese era date (令和/平成/昭和, or R7.10.1 / H31.4.30) as a Gregorian date; ``None`` if
    there is none. A year-and-month date becomes the 1st of that month. ``short=False`` reads only
    the written-out era (令和…年…月), never the R/H short form."""
    if not text:
        return None
    m = ERA_JA.search(text) or (_ERA_SHORT.search(text) if short else None)
    if not m:
        return None
    era, year, month, day = m.group(1), m.group(2), m.group(3), m.group(4)
    y = 1 if year == "元" else int(year)
    return _safe(_ERA_OFFSET[era] + y, int(month), int(day) if day else 1)


def parse_date(value: str | date | datetime | None, *, dayfirst: bool = True) -> date | None:
    """Best-effort date from the formats regulators use (RFC 822, ISO, d/m/Y, 年月日, 년월일,
    Japanese era dates 令和7年10月1日 / R7.10.1)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    d = era_date(s, short=False)
    if d:
        return d
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
    # The short era form (R7.10.1) only after every Gregorian form, so "release R5.3.1,
    # 12/03/2026" is still 12 March 2026.
    d = era_date(s)
    if d:
        return d
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


# What the keyword and category filters drop (6 Nov 2026: a dropped notice was recorded nowhere). The runner
# sets WATCHED to the watchlist's matcher and empties DROPPED before each source: a notice that names a watched
# ingredient is never dropped by a keyword filter, and every drop is kept (collectors/run.py, filtered_item).
WATCHED: Callable[[str], bool] | None = None
DROPPED: list[tuple[str, str]] = []          # (the first line of the dropped text, why)


def dropped(text: str, why: str, *, unless_watched: bool = True) -> bool:
    """True when a filter may drop ``text``; False when it names a watched ingredient (kept instead)."""
    if unless_watched and WATCHED is not None and text and WATCHED(text):
        return False
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    DROPPED.append((first[:300], why))
    return True


def keyword_ok(text: str, include: Iterable[str] | None = None,
               exclude: Iterable[str] | None = None) -> bool:
    """Case-insensitive filter: any include keyword present (if given), no exclude keyword present. A text
    that names a watched ingredient always passes (``WATCHED``); every other drop is noted (``DROPPED``)."""
    low = (text or "").casefold()
    inc = [k.casefold() for k in (include or []) if k]
    exc = [k.casefold() for k in (exclude or []) if k]
    if inc and not any(k in low for k in inc):
        return not dropped(text, "keywords: none of " + ", ".join(inc)[:120])
    hit = next((k for k in exc if k in low), None)
    return hit is None or not dropped(text, f"keyword: {hit}")
