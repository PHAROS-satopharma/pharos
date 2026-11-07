"""PHAROS — New Zealand, Medsafe: data sheets (NZ data sheets follow the EU SmPC numbering).

Source ``spc-medsafe``; country NZ; English. Read from GitHub on 6 Nov 2026 (run 42296657165).

Medsafe's own searches (``/DbSearch/InfoSearch``, the data-sheet and CMI search, and ``/DbSearch/``, the product
search: her two Medsafe pages) answer only through a live JavaScript connection (Blazor Server): a plain request
gets the empty form back, also when the form is posted with its token (checked 6 Nov 2026). What is published
plainly, and read here:

* ``/profs/Datasheet/datasheet.htm``: every data sheet, as ``<a href="p/panadolOsteocaplets.pdf">Panadol Osteo,
  Modified release tablet</a>`` (2,279 links; strengths share one PDF). It names no ingredient.
* ``/other/Updates-Data-sheets-and-CMIs.asp``: each update since January (84 dates in 2026), with its trade name
  and active ingredients, data sheets and CMIs in separate tables.

A data sheet is our ingredient's when its title names the ingredient as a whole word ("APO-Paracetamol 665 mg"),
or when the updates page lists its trade name with the ingredient, as a data sheet or a CMI ("Panadol Osteo":
Paracetamol, its CMI updated 6 Sep 2026). A brand-named
data sheet not updated this year is therefore not found: the database page is marked partial and says so
(migration 0087). The latest update date of a data sheet is its listed version.

The data sheet PDF is split by ``split_numbered`` (4.1–4.9 watched, 10 the date of revision, recorded only).
"""

from __future__ import annotations

import html
import re
from datetime import date

from collectors.core.context import FetchError, ParseError
from collectors.parsers.base import parse_date
from collectors.spc.common import Product, Snapshot, SnapshotError, fetch_label, label_revision, run_cache, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-medsafe"
COUNTRY = "NZ"
LANG = "en"
LIST = "https://www.medsafe.govt.nz/profs/Datasheet/datasheet.htm"
PDF_BASE = "https://www.medsafe.govt.nz/profs/Datasheet/"
UPDATES = "https://www.medsafe.govt.nz/other/Updates-Data-sheets-and-CMIs.asp"

_LINK = re.compile(r'<a\s+href="([a-z0-9]/[^"]+\.pdf)"\s*>([^<]+)</a>', re.I)
_TOKEN = re.compile(
    r"<h3>\s*([^<]*\d{4})\s*</h3>"
    r"|<th[^>]*>(?:(?!</th>).)*?(DATA SHEETS|CONSUMER MEDICINE INFORMATION)(?:(?!</th>).)*</th>"
    r"|<tr>\s*<td[^>]*>((?:(?!</td>).)*)</td>\s*<td[^>]*>((?:(?!</td>).)*)</td>\s*<td[^>]*>((?:(?!</td>).)*)</td>"
    r"\s*</tr>", re.S | re.I)


def _clean(cell: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def trade_of(title: str) -> str:
    """"Panadol Osteo, Modified release tablet" → "Panadol Osteo"."""
    return title.rsplit(",", 1)[0].strip() if "," in title else title.strip()


def parse_list(page: str) -> dict[str, list[str]]:
    """``{pdf path: [titles]}`` of the data-sheet list."""
    out: dict[str, list[str]] = {}
    for href, title in _LINK.findall(page):
        out.setdefault(href, []).append(_clean(title))
    return out


def parse_updates(page: str) -> list[dict]:
    """The rows of the updates page: ``{"date", "trade", "ingredients", "data_sheet"}``, newest first
    (``data_sheet`` False for a CMI row: it still says which ingredient a trade name holds)."""
    rows, day, kind = [], None, None
    for m in _TOKEN.finditer(page):
        if m.group(1):
            day = parse_date(m.group(1).strip())
        elif m.group(2):
            kind = m.group(2).upper()
        elif kind and day and "<strong" not in (m.group(3) or "").lower():
            trade, ingredients = _clean(m.group(3)), _clean(m.group(4))
            if trade:
                rows.append({"date": day, "trade": trade, "ingredients": ingredients,
                             "data_sheet": kind == "DATA SHEETS"})
    return rows


def _page(ctx, url: str, what: str) -> str:
    cache = run_cache(ctx, "medsafe")
    if url not in cache:
        f = ctx.get(url)
        if f.status != 200:
            raise FetchError(f.status, url, f"Medsafe {what}: HTTP {f.status}")
        cache[url] = f.text
    return cache[url]


def _word(term: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.I)


def products_from(sheets: dict[str, list[str]], updates: list[dict], terms: list[str]) -> list[Product]:
    words = [_word(t) for t in terms]
    ours: set[str] = set()                # trade names the updates page gives our ingredient
    by_trade: dict[str, date] = {}        # their latest data-sheet update
    for u in updates:
        if any(w.search(u["ingredients"]) for w in words):
            key = u["trade"].casefold()
            ours.add(key)
            if u["data_sheet"]:
                by_trade[key] = max(by_trade.get(key, u["date"]), u["date"])
    out = []
    for path, titles in sheets.items():
        trades = {trade_of(t).casefold() for t in titles}
        named = any(w.search(t) for w in words for t in titles)
        if not (named or trades & ours):
            continue
        updated = [by_trade[t] for t in trades if t in by_trade]
        out.append(Product(
            national_id=path, product_name=" / ".join(dict.fromkeys(titles)), url=PDF_BASE + path,
            country_code=COUNTRY,
            extra={"updated": str(max(updated)) if updated else None,
                   "found_by": "name" if named else "updates page"}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    sheets = parse_list(_page(ctx, LIST, "data sheet list"))
    if not sheets:
        raise ParseError("Medsafe data sheet list: no data sheet link")
    updates = parse_updates(_page(ctx, UPDATES, "updates page"))
    return products_from(sheets, updates, terms_for(ingredient, "en")[:3])


def listed_version(product: dict) -> str | None:
    """The data sheet's latest date on the updates page (this year's updates only)."""
    return (product.get("extra") or {}).get("updated") or None




def snapshot(ctx, product: dict) -> Snapshot | None:
    url = PDF_BASE + product["national_id"]
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"Medsafe {product['national_id']}: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"Medsafe {product['national_id']}: section {', '.join(missing)} not found")
    return Snapshot(sections=sections, doc_date=label_revision(sections), lang=LANG, source_url=url,
                    original_sha256=f.sha256)
