"""PHAROS — Belgium, FAMHP medicines database (medicinesdatabase.be): the RCP of each nationally authorised product.

Source ``spc-famhp``; country BE; French. Read from GitHub on 6 Nov 2026 (run 42296657165), checked the same day:

* products: ``https://medicinesdatabase.be/download/documents`` (50 MB, ``;``-separated, UTF-8 with a BOM; read
  once a run), one row per pack (73,049 rows, 29,117 products): ``CTI`` (the product, the national id),
  ``CTI Extended`` (the pack), ``Name``, ``Active ingredient`` ("Paracetamol 500 mg; Ibuprofen 200 mg", English
  names), ``ATC code``, ``Human/Veterinary use``, ``URL SKP`` (Dutch SmPC), ``URL RCP`` (French),
  ``Last publication date SPC/leaflet`` (the listed version) and ``Last approval date SPC/leaflet``. A national
  label is served by ``https://app.fagg-afmps.be/pharma-status/api/files/<id>`` (a PDF); a centrally authorised
  product links EMA's product information instead and is left to ``spc-ema-epar``. A product is ours when one
  of its active ingredients names the ingredient's English INN as a whole word, accents and case dropped
  (ivabradine: 4 national products; paracetamol: 157, with 113 distinct RCPs).
* label: the French RCP PDF, split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

from collectors.core.context import FetchError
from collectors.spc.bdpm import fold
from collectors.spc.common import Product, Snapshot, SnapshotError, fetch_label, run_cache, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-famhp"
COUNTRY = "BE"
LANG = "fr"
DOCUMENTS = "https://medicinesdatabase.be/download/documents"
NATIONAL = "https://app.fagg-afmps.be/pharma-status/api/files/"
LIST_BYTES = 150 * 1024 * 1024          # the documents file is 50 MB; the context refuses more than 80 MB


def parse_documents(text: str) -> dict[str, dict]:
    """The human products with a national RCP: ``{CTI: {"name", "ingredients", "atc", "rcp", "published",
    "approved"}}`` (the first pack of each product names it; every pack of a product links one RCP)."""
    csv.field_size_limit(10**8)
    out: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(text, newline=""), delimiter=";"):
        rcp = (r.get("URL RCP") or "").strip()
        cti = (r.get("CTI") or "").strip()
        if not cti or not rcp.startswith(NATIONAL) or (r.get("Human/Veterinary use") or "") != "Human use":
            continue
        out.setdefault(cti, {"name": (r.get("Name") or "").strip(), "ingredients": r.get("Active ingredient") or "",
                             "atc": (r.get("ATC code") or "").split(" ")[0] or None, "rcp": rcp,
                             "published": (r.get("Last publication date SPC/leaflet") or "").strip() or None,
                             "approved": (r.get("Last approval date SPC/leaflet") or "").strip() or None})
    return out


def _products(ctx) -> dict[str, dict]:
    cache = run_cache(ctx, "famhp")
    if "rows" not in cache:
        limit = getattr(ctx, "max_bytes", None)
        if limit is not None:
            ctx.max_bytes = max(limit, LIST_BYTES)
        try:
            f = ctx.get(DOCUMENTS, accept="text/csv,*/*;q=0.5")
        finally:
            if limit is not None:
                ctx.max_bytes = limit
        if f.status != 200:
            raise FetchError(f.status, DOCUMENTS, f"FAMHP documents file: HTTP {f.status}")
        rows = parse_documents(f.content.decode("utf-8-sig", errors="replace"))
        if not rows:
            raise FetchError(f.status, DOCUMENTS, "FAMHP documents file: no national product")
        cache["rows"] = rows
    return cache["rows"]


def holds(ingredients: str, terms: list[str]) -> bool:
    words = [re.compile(rf"(?<![a-z]){re.escape(fold(t))}(?![a-z])") for t in terms if t]
    return any(w.search(fold(part)) for part in ingredients.split(";") for w in words)


def products_from(rows: dict[str, dict], terms: list[str]) -> list[Product]:
    out = []
    for cti, r in rows.items():
        if holds(r["ingredients"], terms):
            out.append(Product(
                national_id=cti, product_name=r["name"] or cti, country_code=COUNTRY, url=r["rcp"],
                extra={"rcp": r["rcp"], "published": r["published"], "approved": r["approved"], "atc": r["atc"]}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    return products_from(_products(ctx), terms_for(ingredient, "en")[:3])


def listed_version(product: dict) -> str | None:
    """The RCP's last publication date in the documents file."""
    return (product.get("extra") or {}).get("published") or None



def snapshot(ctx, product: dict) -> Snapshot | None:
    extra = product.get("extra") or {}
    url = extra.get("rcp")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"FAMHP {product['national_id']} RCP: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"FAMHP {product['national_id']} RCP: section {', '.join(missing)} not found")
    day = extra.get("approved") or extra.get("published")
    return Snapshot(sections=sections, doc_date=date.fromisoformat(day) if day else None, lang=LANG,
                    source_url=url, original_sha256=f.sha256)
