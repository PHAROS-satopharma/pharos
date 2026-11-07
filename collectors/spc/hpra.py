"""PHAROS — Ireland, HPRA "Find a medicine": the SPC of each nationally authorised human medicine.

Source ``spc-hpra``; country IE; English. Read from GitHub on 6 Nov 2026 and locally on 7 Nov 2026.

The HPRA site's own medicine search calls ``https://sfapi.hpra.ie/api/HumanApprovedProducts?code=<key>``, an Azure
Function whose key every visitor's browser gets in the search page's code (``var productsListAPI = "…"``). The
key is read from that page at the start of every run, exactly as the browser does; it is never stored, logged
or printed (``redact`` hides it), and a key that stops working turns the source degraded with that reason —
nothing else is tried (his decision, 6 Nov 2026).

* search: ``POST`` that address with the page's own request (``{"query", "skip", "take", "status": "Authorised",
  "filters": …}``, the page's ``X-Client-App`` header: the time, base64): ``currentFilterCount`` and ``items``,
  each with ``productID``, ``productName``, ``activeProductIngredient`` (``substanceName``), ``productLicense``
  (``licenseNumber`` PA…/EU/…, ``licenseHolderName``), ``emaUrl`` (a centrally authorised product, whose label is
  EMA's and left to ``spc-ema-epar``; it lists no document), ``recentlyUpdatedDatetime`` and
  ``productDocuments`` (``documentType.name`` "Human SPC", "Human PIL", "Human Public Assessment Report": the
  type is taken from this field, never from the file name, which misleads). Ivabradine: 14 products.
* label: the SPC PDF (its address carries its upload time, so a new SPC is a new address: the listed version),
  split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded).
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

from collectors.core.context import FetchError, ParseError
from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_revision, run_cache, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-hpra"
COUNTRY = "IE"
LANG = "en"
SEARCH_PAGE = "https://www.hpra.ie/find-a-medicine/for-human-use/authorised-medicines"
DETAIL = SEARCH_PAGE + "/details/{id}"
TAKE = 100
MAX_PAGES = 20
SPC = "Human SPC"

_API = re.compile(r'var\s+productsListAPI\s*=\s*"(https://sfapi\.hpra\.ie/api/HumanApprovedProducts\?code=[^"]+)"')


def api_address(page: str) -> str | None:
    m = _API.search(page or "")
    return m.group(1) if m else None


def _api(ctx) -> str:
    cache = run_cache(ctx, "hpra")
    if "api" not in cache:
        if hasattr(ctx, "forget"):
            ctx.forget(SEARCH_PAGE)
        f = ctx.get(SEARCH_PAGE, raise_for_status=False)
        if f.status != 200:
            raise FetchError(f.status, SEARCH_PAGE, f"HPRA search page: HTTP {f.status}")
        api = api_address(f.text)
        if not api:
            raise ParseError("HPRA search page: the search's address and key are no longer in the page")
        cache["api"] = api
    return cache["api"]


def payload(term: str, skip: int) -> dict:
    return {"id": None, "skip": skip, "take": TAKE, "query": term, "order": "LastUpdated DESC", "status": "Authorised",
            "filters": {"from": None, "to": None, "routes": None, "placeOfSale": None, "advertisingConditions": None,
                        "marketingAvailability": None, "atcCode": None, "medicineType": None}}


def client_stamp() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"
    return base64.b64encode(now.encode()).decode()


def holds(item: dict, term: str) -> bool:
    word = re.compile(rf"(?<![a-z]){re.escape(fold(term))}(?![a-z])")
    return any(word.search(fold(a.get("substanceName") or "")) for a in item.get("activeProductIngredient") or [])


def spc_of(item: dict) -> dict | None:
    docs = [d for d in item.get("productDocuments") or []
            if ((d.get("documentType") or {}).get("name") or "") == SPC and d.get("documentURL")]
    return docs[-1] if docs else None


def product_from(item: dict, doc: dict) -> Product:
    pid = str(item["productID"])
    lic = item.get("productLicense") or {}
    updated = (item.get("recentlyUpdatedDatetime") or "")[:10] or None
    return Product(
        national_id=pid, product_name=(item.get("productName") or pid).strip(), mah=lic.get("licenseHolderName") or None,
        url=DETAIL.format(id=pid), country_code=COUNTRY,
        extra={"spc": doc["documentURL"], "licence": lic.get("licenseNumber"), "updated": updated,
               "atc": next((a.get("atcCode") for a in reversed(item.get("atcCodes") or []) if a.get("atcCode")), None),
               "market": item.get("marketStatus")})


def discover(ctx, ingredient: dict) -> Listing:
    api = _api(ctx)
    found: dict[str, Product] = {}
    gaps: list[str] = []
    for n, term in enumerate(terms_for(ingredient, "en")[:3], start=1):
        seen = 0
        for page in range(MAX_PAGES):
            r = ctx.post(api, json=payload(term, page * TAKE), headers={"X-Client-App": client_stamp()},
                         accept="application/json", raise_for_status=False)
            if r.status in (401, 403):
                raise FetchError(r.status, api, f"HPRA search refused the key in its own page (HTTP {r.status})")
            if r.status != 200:
                gaps.append(f"term {n} page {page + 1}: HTTP {r.status}")
                break
            try:
                data = r.json()
                items, total = data["items"] or [], int(data["currentFilterCount"])
            except (ValueError, KeyError, TypeError):
                gaps.append(f"term {n} page {page + 1}: not the search answer")
                break
            seen += len(items)
            for it in items:
                if it.get("emaUrl") or not holds(it, term):
                    continue
                doc = spc_of(it)
                if doc is not None:
                    found.setdefault(str(it["productID"]), product_from(it, doc))
            if seen >= total or not items:
                break
        else:
            gaps.append(f"term {n}: more than {MAX_PAGES * TAKE} rows")
    return Listing(found.values(), gaps=gaps)


def listed_version(product: dict) -> str | None:
    """The SPC's address: HPRA gives each uploaded SPC a new one."""
    return (product.get("extra") or {}).get("spc") or None




def snapshot(ctx, product: dict) -> Snapshot | None:
    url = (product.get("extra") or {}).get("spc")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"HPRA {product['national_id']} SPC: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"HPRA {product['national_id']} SPC: section {', '.join(missing)} not found")
    return Snapshot(sections=sections, doc_date=label_revision(sections), lang=LANG, source_url=url,
                    original_sha256=f.sha256)
