"""PHAROS — United Kingdom, MHRA Products: SPC PDFs.

Source ``spc-mhra``; country GB; English.

* Discovery: ``https://products.mhra.gov.uk/search/?search=<INN>&page=1&doc=Spc&rerouteType=0``.
  The page is a static Next.js export whose results are drawn by script (the HTML a plain request
  gets on 4 Nov 2026 says "Loading results for …", fixture ``tests/fixtures/spc-mhra``), so it is
  read with the headless browser, waiting for result links. Each result links the SPC PDF on the
  MHRA document store (``…blob.core.windows.net/docs/<id>``); the result text carries the product
  name and the PL number (in the file name "PL 12345-0001", elsewhere "PL 12345/0001"), which is
  the national id "PL 12345/0001" (else the document id).
* Disclaimer: since at least 5 Nov 2026 the results appear only after the box "I have read and
  understand the disclaimer." is ticked and Agree pressed, on every page load. The owner agreed
  (5 Nov 2026) that PHAROS ticks it on each run (``accept_disclaimer``).
* Only results whose "Active substances:" line names the ingredient are its products: the search is
  full-text. For lornoxicam, all 51 hits on 5 Nov 2026 were fluconazole SPCs that list it among
  their interactions; no UK product contains it (fixture ``search_lornoxicam_agreed.html``).
* Snapshot: the PDF, text by ``collectors.pdf.extract_text``, split by QRD section number.

A challenge page raises ``SourceBlocked`` from ``FetchContext.browser_get``; nothing is bypassed.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from collectors.parsers._html_util import absolute, clean, node_text
from collectors.parsers.base import ParseError, soup
from collectors.spc.common import Product, Snapshot, terms_for
from collectors.spc.sections import WATCHED_EU, split_numbered

SOURCE_ID = "spc-mhra"
COUNTRY = "GB"
LANG = "en"
SEARCH = "https://products.mhra.gov.uk/search/?search={q}&page={page}&doc=Spc&rerouteType=0"
_PL = re.compile(r"(?<![A-Za-z])PL(?:GB|NI)?\s*(\d{5})\s*[-/]\s*(\d{4})(?!\d)", re.I)
_DOC = re.compile(r"blob\.core\.windows\.net/docs/([A-Za-z0-9]+)")
_SUBSTANCES = re.compile(r"Active substances?\s*:\s*(.+)", re.I)
AGREE = "#agree-checkbox"
RESULT_LINK = "a[href*='blob.core.windows.net']"
MAX_PAGES = 5


def accept_disclaimer(page) -> None:
    """Tick "I have read and understand the disclaimer." and press Agree, when it is shown."""
    try:
        page.wait_for_selector(f"{AGREE}, {RESULT_LINK}", timeout=20000)
    except Exception:  # noqa: BLE001 - neither appeared: the caller's own wait reports it
        return
    if page.query_selector(AGREE) is None:
        return
    page.check(AGREE)
    page.click(f"form:has({AGREE}) button[type=submit]")


def substances(line: str) -> list[str]:
    m = _SUBSTANCES.search(line)
    return [clean(x).casefold() for x in m.group(1).split(",")] if m else []


def names_ingredient(found: list[str], terms: list[str]) -> bool:
    wanted_terms = [t.casefold() for t in terms if t]
    return any(re.search(rf"\b{re.escape(t)}\b", s) for s in found for t in wanted_terms)


def parse_results(html, base_url: str, terms: list[str] | None = None) -> list[Product]:
    """``terms`` (the ingredient's English names): keep only results whose active substances name it."""
    doc = soup(html)
    out: list[Product] = []
    seen: set[str] = set()
    for a in doc.select("a[href]"):
        href = a["href"]
        m_doc = _DOC.search(href)
        if not m_doc:
            continue
        holder = a.find_parent(["article", "li", "div"]) or a
        text = node_text(holder)
        if terms is not None:
            lines = [node_text(p) for p in holder.select("p.metadata")] or [text]
            if not names_ingredient([s for line in lines for s in substances(line)], terms):
                continue
        m_pl = _PL.search(text) or _PL.search(node_text(a))
        nid = f"PL {m_pl.group(1)}/{m_pl.group(2)}" if m_pl else m_doc.group(1)
        if nid in seen:
            continue
        seen.add(nid)
        title = a.select_one("p.title")
        name = clean(node_text(title)) if title is not None else ""
        name = name or clean(re.sub(r"^\s*SPC\s*[-:]?\s*", "", node_text(a), flags=re.I)) or nid
        out.append(Product(national_id=nid, product_name=name, url=absolute(href, base_url),
                           country_code=COUNTRY, extra={"doc_id": m_doc.group(1)}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    found: dict[str, Product] = {}
    terms = terms_for(ingredient, "en")
    for term in terms[:2]:
        for page in range(1, MAX_PAGES + 1):
            try:
                f = ctx.browser_get(SEARCH.format(q=quote(term), page=page),
                                    wait_selector=RESULT_LINK, before_wait=accept_disclaimer)
            except ParseError:      # no (more) results: the selector never appeared
                break
            if not parse_results(f, f.final_url):
                break               # a page without results: the end of the list
            for p in parse_results(f, f.final_url, terms):
                found.setdefault(p.national_id, p)
    return list(found.values())


def wanted(section: str) -> bool:
    return section == "10" or section in WATCHED_EU


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = product.get("url")
    if not url:
        return None
    f = ctx.get(url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        return None
    from collectors.pdf import extract_text

    text, _m, _w = extract_text(f.content, LANG)
    sections = {k: v for k, v in split_numbered(text).items() if wanted(k)}
    if not sections:
        return None
    return Snapshot(sections=sections, lang=LANG, source_url=url, original_sha256=f.sha256)
