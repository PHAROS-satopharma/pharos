"""PHAROS — Spain, CIMA (AEMPS) REST API: ficha técnica per section.

Source ``spc-cima``; country ES; Spanish. Verified 4 Nov 2026 with lornoxicam (7 products):

* products: ``https://cima.aemps.es/cima/rest/medicamentos?atc=<ATC>`` (preferred, the ATC code is
  the ingredient's identity anchor) or ``?practiv1=<Spanish INN>``; answer
  ``{"totalFilas", "pagina", "tamanioPagina", "resultados": [{"nregistro", "nombre", "labtitular",
  "estado": {"aut", "rev"?}, "docs": [{"tipo": 1, "url", "urlHtml", "secc": true, "fecha"}]}]}``.
  ``tipo`` 1 is the ficha técnica (SmPC), 2 the prospecto. ``estado.rev`` is a revocation date —
  revoked products are skipped. ``fecha`` (ms since epoch) is the document date.
* sections: ``/cima/rest/docSegmentado/secciones/1?nregistro=<n>`` → ``[{"seccion": "4.4",
  "titulo": "Advertencias y precauciones especiales de empleo", "orden"}]``;
  ``/cima/rest/docSegmentado/contenido/1?nregistro=<n>&seccion=4.4`` → the section as HTML.

Only the watched sections (4.1–4.9 and their sub-sections) and section 10 are fetched: about nine
requests per product, one per second. Products without a segmented ficha técnica (``secc`` false),
or whose section list does not answer, are snapshotted from the full HTML ``urlHtml`` split by
section number. The two ways give different keys and texts, so the snapshot records its ``method``
(``"sections"`` or ``"html"``) and ``run.py`` only diffs it against a snapshot read the same way —
a fallback week and the week the API recovers are never label changes. A section that is listed but
cannot be read raises ``SnapshotError`` (a partial snapshot would read as removed sections).
A product found for two ingredients is read twice in one run; the second read gets 304 from the
context and reuses the first answer (``common.get_reusing``).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import logging

from collectors.core.context import FetchError, ParseError
from collectors.parsers._html_util import block_text
from collectors.parsers.base import soup
from collectors.spc.common import Product, Snapshot, SnapshotError, get_reusing, terms_for
from collectors.spc.sections import WATCHED_EU, split_numbered

SOURCE_ID = "spc-cima"
COUNTRY = "ES"
LANG = "es"
API = "https://cima.aemps.es/cima/rest"
PAGE_SIZE = 200
SECTIONS = "sections"        # Snapshot.method: the per-section API
FULL_HTML = "html"           # Snapshot.method: the full ficha técnica HTML split by number

log = logging.getLogger(__name__)


MADRID = ZoneInfo("Europe/Madrid")


def _ms_date(ms) -> date | None:
    # The date in Spain: a document dated just after midnight in Madrid is still the day before in UTC.
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone(MADRID).date()
    except (TypeError, ValueError, OverflowError):
        return None


def products_from(data: dict, *, include_revoked: bool = False) -> list[Product]:
    out: list[Product] = []
    for r in data.get("resultados") or []:
        if not include_revoked and (r.get("estado") or {}).get("rev"):
            continue
        ft = next((d for d in r.get("docs") or [] if d.get("tipo") == 1), None)
        out.append(Product(
            national_id=str(r["nregistro"]), product_name=r.get("nombre") or str(r["nregistro"]),
            mah=r.get("labtitular"),
            url=f"https://cima.aemps.es/cima/publico/detalle.html?nregistro={r['nregistro']}",
            country_code=COUNTRY,
            extra={"ft_html": (ft or {}).get("urlHtml"), "ft_pdf": (ft or {}).get("url"),
                   "segmented": bool((ft or {}).get("secc")),
                   "ft_date": str(_ms_date((ft or {}).get("fecha")) or "") or None}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    # The ATC code finds the single-ingredient products; the Spanish INN (``practiv1``) also finds the
    # combinations, filed under their own ATC codes (paracetamol with codeine, N02AJ06).
    queries = []
    if ingredient.get("atc_code"):
        queries.append(f"atc={ingredient['atc_code']}")
    queries += [f"practiv1={t.upper()}" for t in terms_for(ingredient, "es")[:3]]
    found: dict[str, Product] = {}
    for q in queries:
        page = 1
        while True:
            url = f"{API}/medicamentos?{q}&pagina={page}"
            f = get_reusing(ctx, url, accept="application/json")
            if f.status != 200:
                # a page that did not answer: the discovery fails, never a list cut short (which would
                # switch off every product past it)
                raise FetchError(f.status, url, f"CIMA product list page {page}: HTTP {f.status}")
            data = f.json()
            for p in products_from(data):
                found.setdefault(p.national_id, p)
            total = int(data.get("totalFilas") or 0)
            if page * int(data.get("tamanioPagina") or PAGE_SIZE) >= total:
                break
            page += 1
    return list(found.values())


def wanted(section: str) -> bool:
    parent = ".".join(section.split(".")[:2])
    return section == "10" or section in WATCHED_EU or parent in WATCHED_EU


def section_text(html: str) -> str:
    return block_text(soup(f"<div>{html}</div>"))


def segmented_sections(ctx, n: str) -> dict[str, str] | None:
    """The watched sections from the per-section API, or None when it has no section list."""
    f = get_reusing(ctx, f"{API}/docSegmentado/secciones/1?nregistro={n}",
                    accept="application/json")
    if f.status != 200 or not f.content.strip().startswith(b"["):
        return None
    sections: dict[str, str] = {}
    for s in f.json():
        key = str(s.get("seccion") or "")
        if not key or not wanted(key):
            continue
        c = get_reusing(ctx, f"{API}/docSegmentado/contenido/1?nregistro={n}&seccion={key}",
                        accept="text/html")
        if c.status != 200:
            raise SnapshotError(f"CIMA {n} section {key}: HTTP {c.status}")
        sections[key] = section_text(c.text)
    return sections or None


def snapshot(ctx, product: dict) -> Snapshot | None:
    n = product["national_id"]
    extra = product.get("extra") or {}
    method, source_url = SECTIONS, f"{API}/docSegmentado/secciones/1?nregistro={n}"
    sections = segmented_sections(ctx, n)
    if not sections:
        method = FULL_HTML
        if extra.get("segmented"):
            log.warning("CIMA %s: no section list; the full ficha técnica is read instead", n)
        html_url = extra.get("ft_html") or f"https://cima.aemps.es/cima/dochtml/ft/{n}/FT_{n}.html"
        g = get_reusing(ctx, html_url)
        source_url = html_url
        if g.status != 200:
            raise SnapshotError(f"CIMA {n} ficha técnica: HTTP {g.status}")
        sections = {k: v for k, v in split_numbered(block_text(soup(g))).items() if wanted(k)}
        if not sections:
            raise ParseError(f"CIMA {n}: no numbered section in the ficha técnica HTML")
    doc_date = None
    if extra.get("ft_date"):
        try:
            doc_date = date.fromisoformat(extra["ft_date"])
        except ValueError:
            doc_date = None
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, method=method,
                    source_url=source_url)
