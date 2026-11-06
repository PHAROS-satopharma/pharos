"""PHAROS — United States, DailyMed (NLM) structured product labels.

Source ``spc-dailymed``; country US; English.

* Discovery: ``https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name=<INN>&doctype=34391-3&pagesize=100&page=<n>``
  → ``{"data": [{"setid", "title", "spl_version", "published_date"}], "metadata": {"total_pages"}}``.
  ``doctype`` 34391-3 (LOINC "human prescription drug label") keeps out veterinary labels (meloxicam,
  5 Nov 2026: 186 labels instead of 209); every page is read, up to ``MAX_PAGES`` (acetaminophen has 765
  prescription labels, 6 Nov 2026: the old cap of 5 pages lost 265 of them). Over-the-counter labels
  (doctype 34390-5) are watched when FDA approves the label itself: an NDA, an ANDA or an NDA authorized
  generic (``OTC_APPROVED``; 6 Nov 2026: acetaminophen 292, guaifenesin 396, phenylephrine 8). The OTC
  monograph labels (about 3,700 store brands of acetaminophen alone) are not read: their text is FDA's
  monograph, which changes by an FDA order, not by a label of their own. Titles are kept as published.
  The lists are searched by the ingredient's RxNorm code (``rxcui=``, ``ingredient.rxcui``) and by its first
  three English names. The code finds the labels whatever their name: paracetamol's names are not the US
  name, and found nothing (0 of acetaminophen's 765 prescription labels, 6 Nov 2026), while ``rxcui=161``
  finds 791. A name still finds the odd label not coded to RxNorm (levofloxacin: 144 by name, 143 by code).
  (An ingredient with no US product, such as lornoxicam, simply yields none.) A page that does not
  answer 200 fails the discovery: a partial list would switch off the products it missed.
* Snapshot: ``https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/<setid>.xml`` (HL7 SPL,
  namespace ``urn:hl7-org:v3``). Sections are found by LOINC code
  (``section/code/@code``, mapped in ``sections.US_LOINC``) and their text is every ``text``
  node below them. ``effectiveTime/@value`` (YYYYMMDD) is the label date.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote
from xml.etree import ElementTree as ET

from collectors.core.context import FetchError
from collectors.spc.common import Product, Snapshot, SnapshotError, fetch_label, terms_for
from collectors.spc.sections import US_LOINC

SOURCE_ID = "spc-dailymed"
COUNTRY = "US"
LANG = "en"
API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
NS = {"v3": "urn:hl7-org:v3"}
HUMAN_RX = "34391-3"  # LOINC document type: human prescription drug label
HUMAN_OTC = "34390-5"  # LOINC document type: human OTC drug label
# The OTC labels FDA approves one by one (DailyMed marketing categories): NDA, ANDA, NDA authorized generic.
OTC_APPROVED = ("C73594", "C73584", "C73605")
MAX_PAGES = 40       # 4,000 labels per list: a bound against a runaway answer, not a cut of a real list
# Snapshot.method: since 7 Nov 2026 the old-format PRECAUTIONS and Recent Major Changes are read too. A snapshot
# read with them is compared only with one read the same way: the first one is a new baseline, so a section
# that was simply never read before never alerts as a label change.
SECTIONS_2 = "spl-sections-2"


def lists(q: str) -> list[tuple[str, str | None]]:
    """The label lists read for one search (``drug_name=…`` or ``rxcui=…``): (query, OTC marketing category)."""
    return [(f"{q}&doctype={HUMAN_RX}", None)] + [
        (f"{q}&doctype={HUMAN_OTC}&marketing_category_code={c}", c) for c in OTC_APPROVED]


def searches(ingredient: dict) -> list[str]:
    """The ingredient's RxNorm code first, then its first three English names."""
    out = [f"rxcui={quote(str(ingredient['rxcui']))}"] if ingredient.get("rxcui") else []
    return out + [f"drug_name={quote(term)}" for term in terms_for(ingredient, "en")[:3]]


def discover(ctx, ingredient: dict) -> list[Product]:
    found: dict[str, Product] = {}
    for search in searches(ingredient):
        for query, otc in lists(search):
            _read_list(ctx, query, otc, found)
    return list(found.values())


def _read_list(ctx, query: str, otc: str | None, found: dict[str, Product]) -> None:
    page = 1
    while page <= MAX_PAGES:
        url = f"{API}/spls.json?{query}&pagesize=100&page={page}"
        f = ctx.get(url, accept="application/json")
        if f.status != 200:
            raise FetchError(f.status, url, f"DailyMed label list {url}: HTTP {f.status}")
        data = f.json()
        for row in data.get("data") or []:
            setid = row.get("setid")
            if not setid or setid in found:
                continue
            found[setid] = Product(
                national_id=setid, product_name=(row.get("title") or setid).strip(),
                url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
                country_code=COUNTRY,
                extra={"spl_version": row.get("spl_version"),
                       "published_date": row.get("published_date"),
                       **({"otc_category": otc} if otc else {})})
        total = int((data.get("metadata") or {}).get("total_pages") or 1)
        if page >= total:
            break
        if page >= MAX_PAGES:
            # a partial list would switch off every label it did not reach: the discovery fails instead
            raise FetchError(200, url, f"DailyMed label list {url}: {total} pages, more than {MAX_PAGES}")
        page += 1


def listed_version(product: dict) -> str | None:
    v = (product.get("extra") or {}).get("spl_version")
    return str(v) if v not in (None, "") else None


def _text(node) -> str:
    parts = []
    for t in node.iter():
        if t.text and t.text.strip():
            parts.append(t.text.strip())
        if t.tail and t.tail.strip():
            parts.append(t.tail.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def parse_spl(xml: bytes) -> tuple[dict[str, str], date | None]:
    root = ET.fromstring(xml)
    sections: dict[str, str] = {}
    for sec in root.iter("{urn:hl7-org:v3}section"):
        code = sec.find("v3:code", NS)
        key = US_LOINC.get(code.get("code")) if code is not None else None
        if not key:
            continue
        texts = [_text(t) for t in sec.iter("{urn:hl7-org:v3}text")]
        body = "\n".join(t for t in texts if t)
        if body:
            sections[key] = (sections[key] + "\n" + body) if key in sections else body
    eff = root.find("v3:effectiveTime", NS)
    when = None
    if eff is not None and re.fullmatch(r"\d{8}", eff.get("value", "")[:8] or ""):
        v = eff.get("value")[:8]
        try:
            when = date(int(v[:4]), int(v[4:6]), int(v[6:8]))
        except ValueError:
            when = None
    return sections, when


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = f"{API}/spls/{product['national_id']}.xml"
    # DailyMed answers HTTP 406 to "Accept: application/xml" alone (6 Nov 2026: every US label of the day's
    # label watch); with a wildcard after it, it serves the same XML
    f = fetch_label(ctx, url, accept="application/xml, */*;q=0.8")
    if f.status != 200 or not f.content:
        raise SnapshotError(f"DailyMed {product['national_id']}: HTTP {f.status}, empty label")
    try:
        sections, when = parse_spl(f.content)
    except ET.ParseError as exc:
        raise SnapshotError(f"DailyMed {product['national_id']}: the label XML does not parse ({exc})") from None
    if not sections:
        return None
    return Snapshot(sections=sections, doc_date=when, lang=LANG, source_url=url,
                    original_sha256=f.sha256, method=SECTIONS_2)
