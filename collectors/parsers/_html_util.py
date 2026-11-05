"""PHAROS — shared helpers for the A2 HTML, browser and e-mail parsers.

Builds on ``collectors.parsers.base`` (A1) and adds what the national regulators need:

* ``local_date(text, lang)`` — dates as each regulator writes them, in its own language:
  "PUBLIÉ LE 04/11/2026", "02.november 2026", "8. oktober 2026", "Október 2026", "29 September 2026",
  "October 27, 2026", "Nov-2026", "Jan - 2026", "05/2026", "2026年10月27日", "2026年4月", "2026-11-04",
  "12 ott 2026", "3 févr. 2026", "out 2026" (pt), and Japanese era dates "令和7年10月1日", "R7.10.1".
  A month-and-year date becomes the 1st of that month.
* ``clean`` / ``node_text`` — whitespace-normalised text, titles kept exactly as published.
* ``pages_to_read(ctx, source)`` — ``options.max_pages`` (default 1) on a normal run,
  ``options.backfill_pages`` (default 5) on a backfill.
* ``keep(source, title, body, lang=)`` — ``options.include_keywords`` / ``options.exclude_keywords``,
  each a list, or ``{lang: [...]}`` for a source that reads pages in several languages.
* ``require(rows, fetched, marker)`` — the "never return a silently empty list" rule: no rows and no
  marker of an empty listing means the page changed shape → ``ParseError``.

Nothing here translates anything: every regulator is screened in its own language.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Iterable

from collectors.parsers.base import (FetchContext, Fetched, ParseError, SourceConfig, absolute,
                                     era_date, keyword_ok, parse_date)

__all__ = ["MONTHS", "absolute", "block_text", "clean", "column", "fill_detail", "keep", "links_in",
           "local_date", "node_text", "pages_to_read", "require", "slug_id", "table_records"]

# Month names (lower-case, accents kept) → month number, for every language A2 reads.
_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("january", "jan", "janvier", "janv", "gennaio", "januar", "jänner", "janúar", "janeiro",
        "januari", "enero", "ene", "tammikuu", "tammikuuta"),
    2: ("february", "feb", "février", "fevrier", "févr", "fevr", "febbraio", "februar", "febrúar",
        "fevereiro", "fev", "februari", "febrero", "helmikuu", "helmikuuta"),
    3: ("march", "mar", "mars", "marzo", "märz", "marts", "mars", "março", "marco", "maart",
        "maaliskuu", "maaliskuuta"),
    4: ("april", "apr", "avril", "avr", "aprile", "apríl", "abril", "abr", "huhtikuu",
        "huhtikuuta"),
    5: ("may", "mai", "maggio", "maí", "maio", "maj", "mei", "mayo", "toukokuu", "toukokuuta"),
    6: ("june", "jun", "juin", "giugno", "giu", "juni", "júní", "junho", "junio", "kesäkuu",
        "kesäkuuta"),
    7: ("july", "jul", "juillet", "juil", "luglio", "lug", "juli", "júlí", "julho", "julio",
        "heinäkuu", "heinäkuuta"),
    8: ("august", "aug", "août", "aout", "agosto", "ágúst", "augusti", "augustus", "elokuu",
        "elokuuta"),
    9: ("september", "sep", "sept", "septembre", "settembre", "setembro", "septiembre", "syyskuu",
        "syyskuuta"),
    10: ("october", "oct", "octobre", "ottobre", "ott", "oktober", "október", "outubro", "octubre",
         "okt", "lokakuu", "lokakuuta"),
    11: ("november", "nov", "novembre", "nóvember", "novembro", "noviembre", "marraskuu",
         "marraskuuta"),
    12: ("december", "dec", "décembre", "decembre", "déc", "dicembre", "dic", "dezember",
         "desember", "desember", "dezembro", "diciembre", "dez", "des", "joulukuu", "joulukuuta"),
}
MONTHS: dict[str, int] = {name: num for num, names in _MONTH_NAMES.items() for name in names}

# Abbreviations that are also ordinary English (or other) words — "out", "set", "ago", "gen", "mag"
# — count as a month only on a page in the language that uses them, so "carried out 2026" on an
# English page is never read as October 2026.
_LANG_MONTHS: dict[str, dict[str, int]] = {
    "it": {"gen": 1, "mag": 5, "ago": 8, "set": 9},
    "es": {"ago": 8},
    "pt": {"ago": 8, "set": 9, "out": 10},
}

_WORD = r"([A-Za-zÀ-ÿ]+)\.?"
_D_MON_Y = re.compile(r"\b(\d{1,2})\s*\.?\s*" + _WORD + r"\s*,?\s*(\d{4})\b")      # 8. oktober 2026
_MON_D_Y = re.compile(r"\b" + _WORD + r"\s+(\d{1,2})(?:st|nd|rd|th)?\s*,\s*(\d{4})\b")  # October 27, 2026
_MON_Y = re.compile(r"\b" + _WORD + r"\s*[-–/ ]\s*(\d{4})\b")                        # Nov-2026, Oktober 2026
_M_Y = re.compile(r"(?<![\d/.])(\d{1,2})\s*[/.-]\s*(\d{4})\b(?![/.]\d)")             # 05/2026
_JA_YM = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月(?!\s*\d)")                        # 2026年4月
_KO_YM = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월(?!\s*\d)")


def _month(word: str, lang: str | None = None) -> int | None:
    w = word.casefold().rstrip(".")
    if w in MONTHS:
        return MONTHS[w]
    primary = (lang or "").split("-")[0].casefold()
    return _LANG_MONTHS.get(primary, {}).get(w)


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def local_date(text: str | None, lang: str | None = None) -> date | None:
    """Parse a regulator's date as written in its own language. ``None`` when there is none."""
    if not text:
        return None
    s = clean(text)
    # Japanese era dates (令和7年10月1日, 令和元年5月) before anything else; the short form
    # (R7.10.1) only on a Japanese page and only when no Gregorian date is there.
    d = era_date(s, short=(lang or "").startswith("ja") and not re.search(r"\d{4}", s))
    if d:
        return d
    # Full numeric and CJK dates first (base.parse_date covers d/m/Y, Y-m-d, 年月日, 년월일).
    if re.search(r"\d{4}\s*[年년]\s*\d{1,2}\s*[月월]\s*\d{1,2}", s) or re.search(
            r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b|\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b", s):
        d = parse_date(s, dayfirst=not (lang or "").startswith("en-US"))
        if d:
            return d
    for m in _D_MON_Y.finditer(s):
        mon = _month(m.group(2), lang)
        if mon:
            return _safe(int(m.group(3)), mon, int(m.group(1)))
    for m in _MON_D_Y.finditer(s):
        mon = _month(m.group(1), lang)
        if mon:
            return _safe(int(m.group(3)), mon, int(m.group(2)))
    for m in _MON_Y.finditer(s):
        mon = _month(m.group(1), lang)
        if mon:
            return _safe(int(m.group(2)), mon, 1)
    for rx in (_JA_YM, _KO_YM):
        m = rx.search(s)
        if m:
            return _safe(int(m.group(1)), int(m.group(2)), 1)
    m = _M_Y.search(s)
    if m and 1 <= int(m.group(1)) <= 12:
        return _safe(int(m.group(2)), int(m.group(1)), 1)
    return None


_WS = re.compile(r"[\s ​  ]+")


def clean(text: str | None) -> str:
    """Collapse whitespace (incl. no-break spaces); nothing else is changed."""
    return _WS.sub(" ", text or "").strip()


def node_text(node, sep: str = " ") -> str:
    """Clean text of a BeautifulSoup node ('' for None)."""
    if node is None:
        return ""
    return clean(node.get_text(sep))


def pages_to_read(ctx: FetchContext, source: SourceConfig, *, default: int = 1,
                  backfill_default: int = 5) -> int:
    opts = source.options or {}
    if getattr(ctx, "backfill", False):
        return max(1, int(opts.get("backfill_pages", backfill_default)))
    return max(1, int(opts.get("max_pages", default)))


def _for_lang(keywords, lang: str | None):
    """A keyword list, or the list for ``lang`` from ``{lang: [...]}`` (a language not listed: none)."""
    if isinstance(keywords, dict):
        return keywords.get((lang or "").split("-")[0]) or []
    return keywords


def keep(source: SourceConfig, *texts: str | None, lang: str | None = None) -> bool:
    """``options.include_keywords`` (any must appear) and ``options.exclude_keywords`` (none may).

    A source reading French and Dutch pages gives ``{"fr": [...], "nl": [...]}``: one list for both
    would drop every item of the other language without a word."""
    opts = source.options or {}
    joined = " ".join(t for t in texts if t)
    return keyword_ok(joined, _for_lang(opts.get("include_keywords"), lang),
                      _for_lang(opts.get("exclude_keywords"), lang))


def require(rows: Iterable, fetched: Fetched, *, marker: str | None = None,
            empty_markers: Iterable[str] = ()) -> None:
    """Raise ``ParseError`` when a page loaded but none of the expected rows is there.

    ``marker`` is a string the healthy page always contains (a container id or class); if it is
    present and the page also carries one of ``empty_markers`` ("Aucun résultat"…), an empty list is
    genuine.
    """
    if list(rows):
        return
    text = fetched.text if fetched.content else ""
    if any(m and m in text for m in empty_markers):
        return
    hint = f" (marker {marker!r} {'present' if marker and marker in text else 'missing'})" \
        if marker else ""
    raise ParseError(f"no rows recognised at {fetched.final_url}{hint}")


_DROP = ("script", "style", "noscript", "nav", "form", "svg", "iframe", "template", "button")


def block_text(tag) -> str:
    """Readable text of one node (line breaks kept, boilerplate tags dropped), without mutating it."""
    if tag is None:
        return ""
    import copy

    node = copy.copy(tag)
    for t in node.find_all(_DROP):
        t.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    lines = [clean(ln) for ln in node.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def links_in(nodes, base_url: str, *, patterns: Iterable[str] = (".pdf",)) -> list[str]:
    """Absolute hrefs inside ``nodes`` whose lower-cased href contains one of ``patterns``."""
    out: list[str] = []
    pats = tuple(p.lower() for p in patterns)
    for node in nodes:
        if node is None:
            continue
        anchors = [node] if getattr(node, "name", None) == "a" else node.select("a[href]")
        for a in anchors:
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("mailto:", "javascript:", "#", "tel:")):
                continue
            if any(p in href.lower() for p in pats):
                url = absolute(href, base_url)
                if url not in out:
                    out.append(url)
    return out


def fill_detail(item, fetched: Fetched, body_selector: str, *,
                attach_selector: str | None = None,
                patterns: Iterable[str] = (".pdf",)):
    """Fill ``item.body_text`` from every node matching ``body_selector`` and add attachment links
    found in those nodes (or in ``attach_selector``). Returns the item."""
    from collectors.parsers.base import soup

    if fetched.status != 200 or not fetched.content:
        return item
    doc = soup(fetched)
    nodes = doc.select(body_selector)
    text = "\n\n".join(t for t in (block_text(n) for n in nodes) if t)
    if text:
        item.body_text = text
    scope = doc.select(attach_selector) if attach_selector else nodes
    for url in links_in(scope, fetched.final_url, patterns=patterns):
        if url not in item.attachment_urls:
            item.attachment_urls.append(url)
    return item


def table_records(table, header_hints: Iterable[str] = ()):
    """Yield ``(cells, header)`` for each data row of ``table``.

    ``header`` is the list of lower-cased column labels, taken from ``th`` cells or, when the table
    has none, from the first row if it contains one of ``header_hints`` (or is all bold). Rows
    spanning fewer cells than the header (rowspan) are yielded as they are.
    """
    header: list[str] = []
    hints = tuple(h.casefold() for h in header_hints)
    for tr in table.find_all("tr"):
        ths = tr.find_all("th", recursive=False)
        tds = tr.find_all("td", recursive=False)
        if ths and not tds:
            header = [node_text(c).casefold() for c in ths]
            continue
        if not header and tds:
            labels = [node_text(c).casefold() for c in tds]
            bold = all(c.find(["strong", "b"]) is not None and not c.find("a") for c in tds)
            if bold or (hints and any(h in " ".join(labels) for h in hints)
                        and not tr.find("a", href=True)):
                header = labels
                continue
        if tds:
            yield tds, header


def column(header: list[str], *names: str, default: int | None = None) -> int | None:
    """Index of the first header label containing one of ``names`` (lower-case)."""
    for i, label in enumerate(header):
        if any(n in label for n in names):
            return i
    return default


_SLUG = re.compile(r"[^A-Za-z0-9._~-]+")


def slug_id(url: str) -> str:
    """A stable external id from a URL: path and query, no scheme/host/fragment."""
    from urllib.parse import urlsplit

    p = urlsplit(url)
    tail = p.path.rstrip("/") + (("?" + p.query) if p.query else "")
    return tail or url
