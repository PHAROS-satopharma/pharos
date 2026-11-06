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

import logging
import re
from urllib.parse import quote

from collectors.parsers._html_util import absolute, clean, node_text
from collectors.parsers.base import ParseError, soup
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, terms_for
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
MAX_PAGES = 40          # per search: 6 Nov 2026 the old 5 pages of 2 names cut paracetamol's list
MAX_TERMS = 4

log = logging.getLogger(__name__)


class DisclaimerNotAccepted(RuntimeError):
    """The disclaimer was still on the page after Agree: the results could not be reached."""


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
    try:
        page.wait_for_selector(AGREE, state="detached", timeout=15000)
    except Exception:  # noqa: BLE001 - still there: say so instead of reading it as "no results"
        raise DisclaimerNotAccepted("MHRA disclaimer still shown after Agree; results not reached") from None


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
        title = a.select_one("p.title")
        name = clean(node_text(title)) if title is not None else ""
        name = name or clean(re.sub(r"^\s*SPC\s*[-:]?\s*", "", node_text(a), flags=re.I))
        # without a PL number, the product's name: the document id changes with every new PDF, and a
        # revised SPC would read as a new product (and the old one as withdrawn)
        nid = (f"PL {m_pl.group(1)}/{m_pl.group(2)}" if m_pl
               else f"name:{name.casefold()}" if name else m_doc.group(1))
        name = name or nid
        if nid in seen:
            continue
        seen.add(nid)
        out.append(Product(national_id=nid, product_name=name, url=absolute(href, base_url),
                           country_code=COUNTRY, extra={"doc_id": m_doc.group(1)}))
    return out


def discover(ctx, ingredient: dict) -> Listing:
    """Every page of every English name's search, up to ``MAX_PAGES`` each.

    The site draws its results by script, so a page past the last one and a page that did not load in
    time look the same (the result links never appear). A page with fewer hits than the first is the
    last one; after a full page, a page that does not show results is taken as the end, but the list
    is then not known to be complete (``Listing.gaps``), and no product is switched off by it."""
    found: dict[str, Product] = {}
    gaps: list[str] = []
    terms = terms_for(ingredient, "en")
    for n, term in enumerate(terms[:MAX_TERMS], start=1):
        size = 0
        for page in range(1, MAX_PAGES + 1):
            try:
                f = ctx.browser_get(SEARCH.format(q=quote(term), page=page),
                                    wait_selector=RESULT_LINK, before_wait=accept_disclaimer)
            except ParseError:      # no results drawn: past the last page, or the page did not load
                if page > 1:
                    gaps.append(f"name {n} page {page}: no results shown after a full page")
                break
            hits = parse_results(f, f.final_url)
            if not hits:
                break               # a page without results: the end of the list
            mine = parse_results(f, f.final_url, terms)
            log.info("SPC %s %r page %d: %d search hit(s), %d with it as an active substance",
                     SOURCE_ID, term, page, len(hits), len(mine))
            for p in mine:
                found.setdefault(p.national_id, p)
            links = len(set(_DOC.findall(f.text)))    # results on the page, before any dedupe
            size = size or links
            if links < size:
                break               # a short page: the last one
        else:
            gaps.append(f"name {n}: more than {MAX_PAGES} pages")
    return Listing(found.values(), gaps=gaps)


def wanted(section: str) -> bool:
    return section == "10" or section in WATCHED_EU


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = product.get("url")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"MHRA {product['national_id']} SPC: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _m, _w = extract_text(f.content, LANG)
    sections = {k: v for k, v in split_numbered(text).items() if wanted(k)}
    if not sections:
        return None
    return Snapshot(sections=sections, lang=LANG, source_url=url, original_sha256=f.sha256)
