"""PHAROS — EU centrally authorised products: EPAR product information (Annex I, the SmPC).

Source ``spc-ema-epar``; country EU; English (the authoritative text; EMA publishes every EU
language at ``…-epar-product-information_<xx>.pdf``, readable with ``SPC_EPAR_LANG``).

* Discovery: EMA's medicines JSON report
  ``https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-json-report_en.json``
  (the same family of reports A1 reads for DHPCs and PSUSAs). Rows of category "Human" whose
  ``atc_code_human`` equals the ingredient's ATC code, or whose ``active_substance`` /
  ``inn_common_name`` contains its English INN, and whose ``medicine_status`` is "Authorised".
  Fields used: ``name_of_medicine``, ``ema_product_number`` (EMEA/H/C/…), ``medicine_url``,
  ``marketing_authorisation_developer_applicant_holder``, ``last_updated_date``.
* Snapshot: ``https://www.ema.europa.eu/en/documents/product-information/<slug>-epar-product-information_en.pdf``
  (``<slug>`` = the last path segment of ``medicine_url``), text by ``collectors.pdf.extract_text``,
  cut to Annex I and split by QRD section number (the first SmPC of a multi-strength Annex).

PSUSA "variation" outcomes (A1's ``ema-psusa``) are the trigger for nationally authorised products;
this module only watches the central SmPC text itself.
"""

from __future__ import annotations

import os
from datetime import date

from collectors.spc.common import Product, Snapshot
from collectors.spc.sections import WATCHED_EU, cut_annex_i, split_numbered

SOURCE_ID = "spc-ema-epar"
COUNTRY = "EU"
LANG = os.environ.get("SPC_EPAR_LANG", "en")
REPORT = ("https://www.ema.europa.eu/en/documents/report/"
          "medicines-output-medicines-json-report_en.json")
PI_URL = "https://www.ema.europa.eu/en/documents/product-information/{slug}-epar-product-information_{lang}.pdf"

_report: list[dict] | None = None


def _rows(ctx) -> list[dict]:
    global _report
    if _report is None:
        f = ctx.get(REPORT, accept="application/json")
        data = f.json() if f.status == 200 else []
        if isinstance(data, dict):
            data = data.get("data") or data.get("items") or []
        _report = list(data)
    return _report


def _get(row: dict, *names: str) -> str:
    for n in names:
        v = row.get(n)
        if v:
            return str(v).strip()
    return ""


def products_from(rows: list[dict], ingredient: dict) -> list[Product]:
    atc = (ingredient.get("atc_code") or "").upper()
    inn = (ingredient.get("inn_en") or "").casefold()
    out: list[Product] = []
    for r in rows:
        if _get(r, "category").casefold() not in ("", "human"):
            continue
        if "authoris" not in _get(r, "medicine_status", "authorisation_status").casefold():
            continue
        row_atc = _get(r, "atc_code_human", "atc_code").upper()
        subst = (_get(r, "active_substance") + " " + _get(r, "inn_common_name")).casefold()
        if not ((atc and row_atc.startswith(atc)) or (inn and inn in subst)):
            continue
        url = _get(r, "medicine_url")
        number = _get(r, "ema_product_number", "product_number") or url
        if not number:
            continue
        out.append(Product(
            national_id=number, product_name=_get(r, "name_of_medicine", "medicine_name"),
            mah=_get(r, "marketing_authorisation_developer_applicant_holder",
                     "marketing_authorisation_holder_company_name") or None,
            url=url or None, country_code=COUNTRY,
            extra={"last_updated": _get(r, "last_updated_date", "revision_date") or None}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    return products_from(_rows(ctx), ingredient)


def pi_url(product: dict) -> str | None:
    url = (product.get("url") or "").rstrip("/")
    if not url:
        return None
    return PI_URL.format(slug=url.rsplit("/", 1)[-1], lang=LANG)


def wanted(section: str) -> bool:
    return section == "10" or section in WATCHED_EU


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = pi_url(product)
    if not url:
        return None
    f = ctx.get(url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        return None
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = {k: v for k, v in split_numbered(cut_annex_i(text)).items() if wanted(k)}
    if not sections:
        return None
    last = (product.get("extra") or {}).get("last_updated")
    doc_date = None
    if last:
        try:
            doc_date = date.fromisoformat(str(last)[:10])
        except ValueError:
            doc_date = None
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url,
                    original_sha256=f.sha256)
