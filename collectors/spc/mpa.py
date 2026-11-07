"""PHAROS — Sweden, Läkemedelsverket (MPA) Läkemedelsfakta: the Swedish SmPC of each nationally authorised product.

Source ``spc-mpa``; country SE; Swedish. Read from GitHub on 6 Nov 2026 and locally on 7 Nov 2026:

* search: ``POST https://www.lakemedelsverket.se/api/lmfrest/searchmedprod`` with ``{"substName", "status": "0",
  "take", "skip"}`` (JSON, no key): ``totalCountMedprod`` and ``medprodResults``, one row per strength (``nplId``),
  with ``activeSubstances`` (Swedish names, the salt written into the word: "ivabradinhydroklorid"),
  ``mpStatusLx`` ("1" Godkänd, "2" Avregistrerad) and ``isPimp`` (a parallel import). English and Swedish INNs
  both answer ("carvedilol" and "karvedilol": 192 rows, 33 approved; "ivabradine": 20, combinations included).
* detail: ``GET /api/lmfrest/medprod?id=<nplId>``: ``medProd.documents[]``, each with ``documentType`` ("SmPC",
  "PL", "EPAR"), ``fileName`` (``https://docetp.mpa.se/LMF/…_<documentId>.pdf``), ``nplId`` (every strength the
  document covers) and ``approvedDate``; ``isCentralProcedure`` (the search row's flag is not reliable: false for
  Corlentor), whose label is EMA's and left to ``spc-ema-epar``. A parallel import publishes a leaflet only.
* product: one per SmPC document, keyed by the first strength it covers (the document id changes with each
  version); its ``approvedDate`` is the listed version.
* label: the SmPC PDF, split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded).
"""

from __future__ import annotations


from collectors.parsers.base import parse_date
from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_revision, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-mpa"
COUNTRY = "SE"
LANG = "sv"
SEARCH = "https://www.lakemedelsverket.se/api/lmfrest/searchmedprod"
DETAIL = "https://www.lakemedelsverket.se/api/lmfrest/medprod?id={npl}"
PAGE = "https://www.lakemedelsverket.se/sv/sok-lakemedelsfakta/lakemedel/{npl}"
TAKE = 500
MAX_PAGES = 10


def norm(word: str) -> str:
    """Swedish and English INN spellings alike: "carvedilol"/"karvedilol", "ivabradine"/"ivabradin"."""
    w = fold(word).replace("ph", "f").replace("th", "t").replace("c", "k").replace("y", "i")
    return w[:-1] if w.endswith("e") else w


def holds(substances: list[str], term: str) -> bool:
    """A substance starts with the term ("ivabradinhydroklorid" holds "ivabradine")."""
    t = norm(term)
    return bool(t) and any(norm(s).startswith(t) for s in substances)


def search_terms(ingredient: dict) -> list[str]:
    terms = terms_for(ingredient, "sv", fallback_en=False)[:2]
    en = ingredient.get("inn_en")
    if en and all(norm(en) != norm(t) for t in terms):
        terms.append(en)
    return terms


def search(ctx, term: str, n: int, gaps: list[str]) -> list[dict]:
    rows: list[dict] = []
    for page in range(MAX_PAGES):
        f = ctx.post(SEARCH, json={"substName": term, "status": "0", "take": TAKE, "skip": page * TAKE},
                     accept="application/json", raise_for_status=False)
        if f.status != 200:
            gaps.append(f"term {n} page {page + 1}: HTTP {f.status}")
            return rows
        try:
            data = f.json()
            got, total = data["medprodResults"], int(data["totalCountMedprod"])
        except (ValueError, KeyError, TypeError):
            gaps.append(f"term {n} page {page + 1}: not the search answer")
            return rows
        rows += got
        if len(rows) >= total or not got:
            return rows
    gaps.append(f"term {n}: more than {MAX_PAGES * TAKE} rows")
    return rows


def smpc_of(medprod: dict) -> dict | None:
    docs = [d for d in medprod.get("documents") or [] if d.get("documentType") == "SmPC" and d.get("fileName")]
    return max(docs, key=lambda d: d.get("approvedDate") or "") if docs else None


def product_from(medprod: dict, doc: dict) -> Product:
    npls = sorted((doc.get("nplId") or medprod["nplId"]).split())
    key = npls[0]
    approved = (doc.get("approvedDate") or "")[:10]
    return Product(
        national_id=key, product_name=(medprod.get("medprodName") or key).strip(),
        mah=medprod.get("organizationName") or None, url=PAGE.format(npl=key), country_code=COUNTRY,
        extra={"smpc": doc["fileName"], "document": doc.get("documentId"), "npl_ids": npls,
               "approved": approved if approved > "0001-01-01" else None, "atc": medprod.get("atcCode8"),
               "procedure": medprod.get("procedureTypeText")})


def discover(ctx, ingredient: dict) -> Listing:
    gaps: list[str] = []
    wanted_npl: dict[str, dict] = {}
    for n, term in enumerate(search_terms(ingredient), start=1):
        for r in search(ctx, term, n, gaps):
            if (r.get("mpStatusLx") == "1" and not r.get("isPimp") and r.get("vetHum", "HUM") == "HUM"
                    and holds(r.get("activeSubstances") or [], term)):
                wanted_npl.setdefault(r["nplId"], r)
    found: dict[str, Product] = {}
    covered: set[str] = set()
    for npl in wanted_npl:
        if npl in covered:
            continue
        f = ctx.get(DETAIL.format(npl=npl), accept="application/json", raise_for_status=False)
        if f.status != 200:
            gaps.append(f"product {npl}: HTTP {f.status}")
            continue
        try:
            medprod = f.json()["medProd"]
        except (ValueError, KeyError, TypeError):
            gaps.append(f"product {npl}: not the product answer")
            continue
        if medprod.get("isCentralProcedure") or medprod.get("isPimp"):
            continue
        doc = smpc_of(medprod)
        if doc is None:
            continue
        p = product_from(medprod, doc)
        covered.update(p.extra["npl_ids"])
        found.setdefault(p.national_id, p)
    return Listing(found.values(), gaps=gaps)


def listed_version(product: dict) -> str | None:
    """The SmPC's approval date in Läkemedelsfakta."""
    return (product.get("extra") or {}).get("approved") or None




def snapshot(ctx, product: dict) -> Snapshot | None:
    extra = product.get("extra") or {}
    url = extra.get("smpc")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"MPA {product['national_id']} SmPC: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"MPA {product['national_id']} SmPC: section {', '.join(missing)} not found")
    doc_date = label_revision(sections)
    if doc_date is None and extra.get("approved"):
        doc_date = parse_date(extra["approved"])
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url, original_sha256=f.sha256)
