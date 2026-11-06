"""PHAROS — Austria, BASG Medikamente Info Austria (MiA): the Fachinformation (SmPC) of each national product.

Source ``spc-basg``; country AT; German. Read from GitHub on 6 Nov 2026 and locally on 7 Nov 2026.

MiA is an Angular site whose front end calls ``<apiUrl>/api/v1/medication/search?page=<n>&size=<k>`` with a
bearer token written into its own script (``main-<hash>.js``: ``apiUrl:"…",apiToken:"…"``), which every
visitor's browser receives. The token is read from that script at the start of every run, exactly as the
browser does (the script's name changes with each release, so it is found from the start page); it is never
stored, logged or printed, and a token that stops working turns the source degraded with that reason — nothing
else is tried (his decision, 6 Nov 2026).

* search: ``POST`` with the front end's filter (``{"substance": "Ivabradin", …}``, German INNs, matched to the
  start of the substance: "IVABRADIN HYDROCHLORID"): ``totalItems`` and ``items``, each with ``authNumber``
  (the Zulassungsnummer; "EU/1/…" a centrally authorised product, whose label is EMA's and left to
  ``spc-ema-epar``), ``name``, ``substances``, ``approvalHolder``, ``mrpDcpNumber`` and ``fachInformation``
  (``validityDate``: the listed version). Ivabradine: 24 rows.
* label: ``https://medikamente.basg.gv.at/documents/<Zulassungsnummer>__DOTC_FACH_INFO.pdf`` (open, no token),
  split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded: "Stand der Information").

German names come from ``ingredient_term`` (lang ``de``); without one, the English INN without its final "e"
("ivabradine" → "ivabradin").
"""

from __future__ import annotations

import re

from collectors.core.context import FetchError, ParseError
from collectors.parsers.base import parse_date
from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_revision, run_cache, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-basg"
COUNTRY = "AT"
LANG = "de"
SITE = "https://medikamente.basg.gv.at/"
PDF = SITE + "documents/{znr}__DOTC_FACH_INFO.pdf"
SIZE = 100
MAX_PAGES = 20

_MAIN = re.compile(r'<script[^>]+src="(main-[A-Za-z0-9]+\.js)"')
_BASE = re.compile(r'<base href="([^"]*)"')
_API = re.compile(r'apiUrl:"(https://medikamente\.basg\.gv\.at/[^"]*)"')
_TOKEN = re.compile(r'apiToken:"([^"]+)"')


def front_end(index: str, script: str) -> tuple[str, str] | None:
    """(API address, token) from the front end's script, or None when they are no longer there."""
    api, token = _API.search(script or ""), _TOKEN.search(script or "")
    return (api.group(1).rstrip("/"), token.group(1)) if api and token else None


def _access(ctx) -> tuple[str, str]:
    cache = run_cache(ctx, "basg")
    if "access" not in cache:
        for url in (SITE,):
            if hasattr(ctx, "forget"):
                ctx.forget(url)
        index = ctx.get(SITE, raise_for_status=False)
        main = _MAIN.search(index.text or "") if index.status == 200 else None
        if not main:
            raise ParseError(f"BASG start page: HTTP {index.status}, no front-end script")
        base = (_BASE.search(index.text).group(1) if _BASE.search(index.text) else "/").strip("/")
        script_url = SITE + (f"{base}/" if base else "") + main.group(1)
        if hasattr(ctx, "forget"):
            ctx.forget(script_url)
        script = ctx.get(script_url, raise_for_status=False)
        found = front_end(index.text, script.text if script.status == 200 else "")
        if not found:
            raise ParseError("BASG front end: the API address and token are no longer in its script")
        cache["access"] = found
    return cache["access"]


def german_inn(en: str) -> str:
    word = en.strip()
    return word[:-1] if word.lower().endswith("ine") else word


def search_terms(ingredient: dict) -> list[str]:
    terms = terms_for(ingredient, "de", fallback_en=False)[:2]
    if not terms and ingredient.get("inn_en"):
        terms = [german_inn(ingredient["inn_en"])]
    return terms


def body(term: str) -> dict:
    keys = ("nameAuthNumber", "atcCode", "approvalHolder", "authDateFrom", "authDateTo", "prescriptionStatus",
            "supplyStatus", "domain", "categoryName", "speciesCategory", "species", "batchApprMandatory",
            "excBatchControl", "containsNarcotic", "marketingAvailability", "containsPsycho", "approvedLi", "vaccine")
    return {"substance": term} | {k: None for k in keys}


def holds(substances: list[str], term: str) -> bool:
    t = fold(term)
    return bool(t) and any(fold(s).startswith(t) for s in substances)


def product_from(item: dict) -> Product:
    znr = item["authNumber"].strip()
    fi = item.get("fachInformation") or {}
    return Product(
        national_id=znr, product_name=(item.get("name") or znr).strip(),
        mah=(item.get("approvalHolder") or "").split(",")[0].strip() or None,
        url=PDF.format(znr=znr.replace("/", "_")), country_code=COUNTRY,
        extra={"fi": PDF.format(znr=znr.replace("/", "_")), "valid": fi.get("validityDate"),
               "substances": item.get("substances") or [], "procedure": item.get("mrpDcpNumber")})


def discover(ctx, ingredient: dict) -> Listing:
    api, token = _access(ctx)
    found: dict[str, Product] = {}
    gaps: list[str] = []
    for n, term in enumerate(search_terms(ingredient), start=1):
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            r = ctx.post(f"{api}/api/v1/medication/search?page={page}&size={SIZE}", json=body(term),
                         headers={"Authorization": f"Bearer {token}", "Accept-Language": "DE"},
                         accept="application/json", raise_for_status=False)
            if r.status in (401, 403):
                raise FetchError(r.status, f"{api}/api/v1/medication/search",
                                 f"BASG search refused the token in its own front end (HTTP {r.status})")
            if r.status != 200:
                gaps.append(f"term {n} page {page}: HTTP {r.status}")
                break
            try:
                data = r.json()
                items, total = data["items"] or [], int(data["totalItems"])
            except (ValueError, KeyError, TypeError):
                gaps.append(f"term {n} page {page}: not the search answer")
                break
            seen += len(items)
            for it in items:
                znr = (it.get("authNumber") or "").strip()
                if (znr and not znr.upper().startswith("EU/") and it.get("fachInformation")
                        and holds(it.get("substances") or [], term)):
                    found.setdefault(znr, product_from(it))
            if seen >= total or not items:
                break
        else:
            gaps.append(f"term {n}: more than {MAX_PAGES * SIZE} rows")
    return Listing(found.values(), gaps=gaps)


def listed_version(product: dict) -> str | None:
    """The Fachinformation's validity date in MiA."""
    return (product.get("extra") or {}).get("valid") or None




def snapshot(ctx, product: dict) -> Snapshot | None:
    extra = product.get("extra") or {}
    url = extra.get("fi") or PDF.format(znr=product["national_id"].replace("/", "_"))
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"BASG {product['national_id']} Fachinformation: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"BASG {product['national_id']} Fachinformation: section {', '.join(missing)} not found")
    doc_date = label_revision(sections)
    if doc_date is None and extra.get("valid"):
        doc_date = parse_date(extra["valid"])
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url, original_sha256=f.sha256)
