"""PHAROS — Canada, Health Canada Drug Product Database (DPD): the product monograph of each marketed product.

Source ``spc-hc-dpd``; country CA; English. Read from GitHub on 6 Nov 2026 (run 42296657165); checked the same day
with ivabradine (LANCORA 5 and 7.5 mg, one monograph) and acetaminophen (1,354 products listed, 241 marketed):

* products: ``/api/drug/activeingredient/?lang=en&type=json&ingredientname=<English INN>`` gives every product
  holding the ingredient, in any status (``drug_code``, ``ingredient_name`` "IVABRADINE (IVABRADINE
  HYDROCHLORIDE)"); the search matches inside words, so a product is kept only when its ingredient names the
  term as a whole word. ``/api/drug/drugproduct/?lang=en&type=json&status=2`` is every marketed product in one
  answer (13,385 rows, 3.4 MB; read once a run): brand name, DIN, company, class (human products only) and
  ``last_update_date``, the day the product's record last changed, which moves when a new monograph is filed
  (LANCORA: 2025-06-26, the day its monograph PDF was published), so it is the listed version.
* label: the product's page ``/dpd-bdpp/info?lang=eng&code=<drug_code>`` links its monograph
  ``https://pdf.hres.ca/dpd_pm/<n>.PDF`` under "Product Monograph/Veterinary Labelling", with its date (the date
  of authorization). A product without one (most non-prescription products: 68 of the 96 read on 9 Nov 2026,
  cough and cold remedies) says so on that page, "product monograph is not available": it has no label text,
  published none. A page with neither the link nor that sentence is an error, never a quiet "no label" (a
  changed page would otherwise pass for 96 products without a monograph). Strengths often share one monograph.

The monograph is split by ``sections.split_ca_monograph`` into ``"ca:…"`` keys (the 2020 template's numbered
headings, or the older unnumbered capitals); "Recent Major Label Changes" is a section of its own.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote

from collectors.core.context import FetchError
from collectors.spc.common import Product, Snapshot, SnapshotError, fetch_label, run_cache, terms_for
from collectors.spc.sections import WATCHED_CA, split_ca_monograph

SOURCE_ID = "spc-hc-dpd"
COUNTRY = "CA"
LANG = "en"
API = "https://health-products.canada.ca/api/drug"
INGREDIENT = API + "/activeingredient/?lang=en&type=json&ingredientname={term}"
MARKETED = API + "/drugproduct/?lang=en&type=json&status=2"
INFO = "https://health-products.canada.ca/dpd-bdpp/info?lang=eng&code={code}"

_PM_LINK = re.compile(r'href="(https://pdf\.hres\.ca/dpd_pm/\d+\.PDF)"', re.I)
_PM_NONE = re.compile(r"product\s+monograph\s+is\s+not\s+available", re.I)
_PM_DATE = re.compile(r"Product Monograph/Veterinary Labelling:.*?Date:\s*</strong>\s*<span>\s*(\d{4}-\d{2}-\d{2})",
                      re.S | re.I)


def _json(ctx, url: str, what: str):
    f = ctx.get(url, accept="application/json")
    if f.status != 200:
        raise FetchError(f.status, url, f"Health Canada {what}: HTTP {f.status}")
    return f.json()


def marketed(ctx) -> dict[int, dict]:
    """Every marketed human product, by drug code (read once a run)."""
    cache = run_cache(ctx, "hc-dpd-marketed")
    if "rows" not in cache:
        rows = _json(ctx, MARKETED, "marketed products")
        if not isinstance(rows, list) or not rows:
            raise FetchError(200, MARKETED, "Health Canada marketed products: an empty answer")
        cache["rows"] = {int(r["drug_code"]): r for r in rows
                         if (r.get("class_name") or "").casefold() == "human"}
    return cache["rows"]


def names_term(ingredient_name: str, term: str) -> bool:
    return bool(re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", ingredient_name or "", re.I))


def products_from(ingredient_rows: list[dict], market: dict[int, dict], term: str) -> list[Product]:
    out: dict[int, Product] = {}
    for r in ingredient_rows:
        code = int(r["drug_code"])
        m = market.get(code)
        if m is None or code in out or not names_term(r.get("ingredient_name", ""), term):
            continue
        out[code] = Product(
            national_id=m.get("drug_identification_number") or str(code),
            product_name=" ".join(x for x in (m.get("brand_name"), m.get("descriptor")) if x) or str(code),
            mah=m.get("company_name") or None, url=INFO.format(code=code), country_code=COUNTRY,
            extra={"drug_code": code, "last_update": m.get("last_update_date") or None,
                   "ai_group": m.get("ai_group_no") or None})
    return list(out.values())


def discover(ctx, ingredient: dict) -> list[Product]:
    market = marketed(ctx)
    found: dict[str, Product] = {}
    for term in terms_for(ingredient, "en")[:3]:
        rows = _json(ctx, INGREDIENT.format(term=quote(term)), "active ingredient search")
        for p in products_from(rows if isinstance(rows, list) else [], market, term):
            found.setdefault(p.national_id, p)
    return list(found.values())


def listed_version(product: dict) -> str | None:
    """The product record's last update in the marketed list: a new monograph moves it."""
    return (product.get("extra") or {}).get("last_update") or None


def monograph_link(page: str) -> tuple[str, date | None] | None:
    m = _PM_LINK.search(page)
    if not m:
        return None
    d = _PM_DATE.search(page)
    return m.group(1), (date.fromisoformat(d.group(1)) if d else None)


def wanted(key: str) -> bool:
    return key in WATCHED_CA


def snapshot(ctx, product: dict) -> Snapshot | None:
    code = (product.get("extra") or {}).get("drug_code")
    page = fetch_label(ctx, INFO.format(code=code))
    if page.status != 200:
        raise SnapshotError(f"Health Canada {product['national_id']} product page: HTTP {page.status}")
    link = monograph_link(page.text)
    if not link:
        if _PM_NONE.search(page.text):
            return None                    # Health Canada publishes no monograph for it
        raise SnapshotError(f"Health Canada {product['national_id']} product page: neither a monograph link nor "
                            f"'product monograph is not available'")
    url, doc_date = link
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"Health Canada {product['national_id']} monograph: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = {k: v for k, v in split_ca_monograph(text).items() if wanted(k)}
    if not sections:
        raise SnapshotError(f"Health Canada {product['national_id']} monograph: no section heading found")
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url, original_sha256=f.sha256)
