"""PHAROS — Iceland, Lyfjastofnun Sérlyfjaskrá: the Icelandic SmPC of each nationally authorised human medicine.

Source ``spc-lyfja``; country IS; Icelandic. Read locally on 7 Nov 2026 (the site's sitemap, product pages and
SmPCs answered from GitHub on 6 Nov 2026).

The site's own ATC browser calls ``/api/searchMedicineWithAtc?query=<ATC>*`` (JSON, no key, no sign-in): every
medicine whose ATC code starts with it, each with ``medicinalProductId``, ``name``, ``strength``,
``marketingAuthorizationNumber`` ("IS/1/…", "EU/1/…" a centrally authorised product, whose label is EMA's and left
to ``spc-ema-epar``; it lists only "Heildartexti EU"), ``authorizationStatus`` ("Markaðsleyfi útgefið"; parallel
imports are "Samhliða innflutningur leyfi"), ``category`` ("Lyf fyrir menn"), ``ingredients`` (Latin INNs:
"Carvedilolum INN") and ``documents`` (``type`` "SmPC", ``externalFileName`` ``<id>/<name>.pdf`` under
``/FileRepos/``, ``modifiedOn``). Ivabradine 2 (both central), carvedilol 4, paracetamol 24, guaifenesin 1.

* search: the ingredient's ATC group (its first five characters: "N02BE*"), so that combinations in the same group
  (paracetamol N02BE51) are found too; a medicine is kept when its ATC code is the ingredient's or one of its
  active ingredients is the ingredient. Combinations filed under another group are not found, and an ingredient
  without an ATC code cannot be searched (reported as a gap, so nothing is switched off).
* product: one per SmPC document (strengths share one), keyed by the first medicine id it covers (a new upload
  gets a new document id); the document's id and ``modifiedOn`` are the listed version.
* label: the SmPC PDF, split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded:
  "Dagsetning endurskoðunar textans", "27. febrúar 2020").
"""

from __future__ import annotations

from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_revision
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-lyfja"
COUNTRY = "IS"
LANG = "is"
SITE = "https://www.serlyfjaskra.is"
SEARCH = SITE + "/api/searchMedicineWithAtc?query={atc}*"
FILES = SITE + "/FileRepos/{name}"
PAGE = SITE + "/lyf/{slug}"
AUTHORISED = "Markaðsleyfi útgefið"
HUMAN = "Lyf fyrir menn"
ACTIVE = "Virk innihaldsefni"


def stem(inn_en: str) -> str:
    """The English INN as the start of its Latin name: "ivabradine" → "ivabradin" ("Ivabradinum INN")."""
    word = fold(inn_en or "").strip()
    return word[:-1] if word.endswith("e") else word


def holds(item: dict, ingredient: dict) -> bool:
    if ingredient.get("atc_code") and item.get("atcCategory") == ingredient["atc_code"]:
        return True
    s = stem(ingredient.get("inn_en") or "")
    return bool(s) and any(fold(i.get("name") or "").startswith(s) for i in item.get("ingredients") or []
                           if (i.get("type") or ACTIVE) == ACTIVE)


def smpc_of(item: dict) -> dict | None:
    docs = [d for d in item.get("documents") or [] if d.get("type") == "SmPC" and d.get("externalFileName")]
    return max(docs, key=lambda d: d.get("modifiedOn") or "") if docs else None


def wanted(item: dict) -> bool:
    return (item.get("authorizationStatus") == AUTHORISED and item.get("category", HUMAN) == HUMAN
            and not (item.get("marketingAuthorizationNumber") or "").upper().startswith("EU/"))


def products_from(items: list[dict], ingredient: dict) -> list[Product]:
    by_doc: dict[str, list[tuple[dict, dict]]] = {}
    for it in items:
        doc = smpc_of(it) if wanted(it) and holds(it, ingredient) else None
        if doc is not None:
            by_doc.setdefault(doc["id"], []).append((it, doc))
    out = []
    for group in by_doc.values():
        group.sort(key=lambda p: p[0]["medicinalProductId"].lower())
        first, doc = group[0]
        strengths = dict.fromkeys(f"{it.get('strength') or ''} {it.get('strengthUnit') or ''}".strip()
                                  for it, _ in group if it.get("strength"))
        name = " ".join(x for x in ((first.get("name") or "").strip(), ", ".join(strengths)) if x)
        out.append(Product(
            national_id=first["medicinalProductId"].lower(), product_name=name or first["medicinalProductId"],
            mah=(first.get("marketingAuthorizationHolder") or "").rstrip("*").strip() or None,
            url=PAGE.format(slug=first.get("slug") or first["medicinalProductId"]), country_code=COUNTRY,
            extra={"smpc": FILES.format(name=doc["externalFileName"]), "document": doc["id"],
                   "modified": doc.get("modifiedOn"), "atc": first.get("atcCategory"),
                   "licences": [it.get("marketingAuthorizationNumber") for it, _ in group]}))
    return out


def discover(ctx, ingredient: dict) -> Listing:
    atc = (ingredient.get("atc_code") or "").strip().upper()
    if not atc:
        return Listing([], gaps=["no ATC code: Sérlyfjaskrá is searched by ATC group only"])
    url = SEARCH.format(atc=atc[:5])
    f = ctx.get(url, accept="application/json", raise_for_status=False)
    if f.status != 200:
        return Listing([], gaps=[f"ATC {atc[:5]}: HTTP {f.status}"])
    try:
        items = f.json()
        if not isinstance(items, list):
            raise TypeError
    except (ValueError, TypeError):
        return Listing([], gaps=[f"ATC {atc[:5]}: not the search answer"])
    return Listing(products_from(items, ingredient), gaps=[])


def listed_version(product: dict) -> str | None:
    """The SmPC document's id and its last change in Sérlyfjaskrá."""
    extra = product.get("extra") or {}
    return f"{extra['document']}@{extra.get('modified') or ''}" if extra.get("document") else None


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = (product.get("extra") or {}).get("smpc")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"Sérlyfjaskrá {product['product_name']} SmPC: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"Sérlyfjaskrá {product['product_name']} SmPC: section {', '.join(missing)} not found")
    return Snapshot(sections=sections, doc_date=label_revision(sections), lang=LANG, source_url=url,
                    original_sha256=f.sha256)
