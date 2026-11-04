"""PHAROS — United Kingdom, MHRA Products: SPC PDFs.

Source ``spc-mhra``; country GB; English.

* Discovery: ``https://products.mhra.gov.uk/search/?search=<INN>&page=1&doc=Spc&rerouteType=0``.
  The page is a static Next.js export whose results are drawn by script (the HTML a plain request
  gets on 4 Nov 2026 says "Loading results for …", fixture ``tests/fixtures/spc-mhra``), so it is
  read with the headless browser, waiting for result links. Each result links the SPC PDF on the
  MHRA document store (``…blob.core.windows.net/docs/<id>``); the result text carries the product
  name and the PL number ("PL 12345/0001"), which is the national id (else the document id).
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
_PL = re.compile(r"\bPL(?:GB)?\s*(\d{5})\s*/\s*(\d{4})\b", re.I)
_DOC = re.compile(r"blob\.core\.windows\.net/docs/([A-Za-z0-9]+)")
MAX_PAGES = 5


def parse_results(html, base_url: str) -> list[Product]:
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
        m_pl = _PL.search(text) or _PL.search(node_text(a))
        nid = f"PL {m_pl.group(1)}/{m_pl.group(2)}" if m_pl else m_doc.group(1)
        if nid in seen:
            continue
        seen.add(nid)
        name = clean(re.sub(r"^\s*SPC\s*[-:]?\s*", "", node_text(a), flags=re.I)) or nid
        out.append(Product(national_id=nid, product_name=name, url=absolute(href, base_url),
                           country_code=COUNTRY, extra={"doc_id": m_doc.group(1)}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    found: dict[str, Product] = {}
    for term in terms_for(ingredient, "en")[:2]:
        for page in range(1, MAX_PAGES + 1):
            try:
                f = ctx.browser_get(SEARCH.format(q=quote(term), page=page),
                                    wait_selector="a[href*='blob.core.windows.net']")
            except ParseError:      # no (more) results: the selector never appeared
                break
            got = parse_results(f, f.final_url)
            new = [p for p in got if p.national_id not in found]
            for p in new:
                found[p.national_id] = p
            if not new:
                break
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
