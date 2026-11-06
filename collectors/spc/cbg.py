"""PHAROS — the Netherlands, CBG Geneesmiddeleninformatiebank: SmPC (SPC) of each nationally authorised product.

Source ``spc-cbg``; country NL; Dutch. Her two CBG pages (the information bank in English and in Dutch) are one
database. Read from GitHub on 6 Nov 2026 (run 42296657165), checked the same day:

* products: ``https://www.geneesmiddeleninformatiebank.nl/metadata.csv`` (16.4 MB, refreshed weekly; read once a
  run), ``|``-separated, one row per product (19,569): ``REGISTRATIENUMMER`` (the RVG number, the national id),
  ``SOORT`` (RVG, a national authorisation; RVH, homeopathic; empty, a centrally authorised product, whose SmPC
  is EMA's and is read by ``spc-ema-epar``), ``PRODUCTNAAM``, ``HANDELSVERGUNNINGHOUDER``, ``SMPC_FILENAAM`` (the
  SmPC PDF), ``SMPC_WIJZIG_DATUM`` (its change date, "30-APR-24": the listed version), ``ATC`` ("C01EB17 -
  Ivabradine"), ``WERKZAMESTOFFEN`` (active substances, ``#``-separated, the salt written into the word:
  "IVABRADINEHYDROCHLORIDE"), ``PRODUCTDETAIL_LINK`` and ``SMPC_VORIGE_VERSIE`` / ``SMPC_VORIGE_VORIGE_VERSIE``
  (the two previous SmPC versions, kept by the CBG: ``collectors/spc/replay.py`` compares them).
  A product is ours when one of its substances starts with the ingredient's Dutch or English INN, accents and
  case dropped (ivabradine: 60 rows, with the carvedilol combinations; paracetamol: 278).
* label: the SmPC PDF, split by QRD section number (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded).
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

from collectors.core.context import FetchError
from collectors.spc.bdpm import fold
from collectors.spc.common import Product, Snapshot, SnapshotError, fetch_label, run_cache, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-cbg"
COUNTRY = "NL"
LANG = "nl"
METADATA = "https://www.geneesmiddeleninformatiebank.nl/metadata.csv"
OWN_SMPC = "https://www.geneesmiddeleninformatiebank.nl/"


def parse_metadata(text: str) -> list[dict]:
    csv.field_size_limit(10**8)
    return list(csv.DictReader(io.StringIO(text, newline=""), delimiter="|"))


def _rows(ctx) -> list[dict]:
    cache = run_cache(ctx, "cbg")
    if "rows" not in cache:
        f = ctx.get(METADATA, accept="text/csv,*/*;q=0.5")
        if f.status != 200:
            raise FetchError(f.status, METADATA, f"CBG metadata.csv: HTTP {f.status}")
        rows = parse_metadata(f.content.decode("utf-8-sig", errors="replace"))
        if not rows or "WERKZAMESTOFFEN" not in rows[0]:
            raise FetchError(f.status, METADATA, "CBG metadata.csv: no product rows")
        cache["rows"] = rows
    return cache["rows"]


def cbg_date(value: str | None) -> date | None:
    """ "30-APR-24" → 2024-04-30."""
    try:
        return datetime.strptime((value or "").strip().title(), "%d-%b-%y").date()
    except ValueError:
        return None


def holds(row: dict, needles: list[str]) -> bool:
    return any(fold(s.strip()).startswith(n) for s in (row.get("WERKZAMESTOFFEN") or "").split("#")
               for n in needles)


def products_from(rows: list[dict], terms: list[str]) -> list[Product]:
    needles = [n for n in (fold(t) for t in terms) if n]
    out = []
    for r in rows:
        smpc = (r.get("SMPC_FILENAAM") or "").strip()
        if (r.get("SOORT") or "").strip() != "RVG" or not smpc.startswith(OWN_SMPC) or not holds(r, needles):
            continue
        out.append(Product(
            national_id=r["REGISTRATIENUMMER"].strip(), product_name=(r.get("PRODUCTNAAM") or "").strip(),
            mah=(r.get("HANDELSVERGUNNINGHOUDER") or "").strip() or None,
            url=(r.get("PRODUCTDETAIL_LINK") or "").strip() or None, country_code=COUNTRY,
            extra={"smpc": smpc, "smpc_date": str(cbg_date(r.get("SMPC_WIJZIG_DATUM")) or "") or None,
                   "atc": (r.get("ATC") or "").split(" - ")[0].strip() or None,
                   "previous": (r.get("SMPC_VORIGE_VERSIE") or "").strip() or None}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    terms = terms_for(ingredient, "nl") + [t for t in terms_for(ingredient, "en") if t]
    return products_from(_rows(ctx), terms)


def listed_version(product: dict) -> str | None:
    """The SmPC's change date in metadata.csv."""
    return (product.get("extra") or {}).get("smpc_date") or None



# The stamp across every page of an archived SmPC (``SMPC_VORIGE_VERSIE``), read into the text where it falls.
ARCHIVE_STAMP = re.compile(r"Oude versie")
_ARCHIVE_DATE = re.compile(r"_smpc(?:_[a-z]{2})?_(\d{4})(\d{2})(\d{2})_v\d+\.pdf$", re.I)


def archive_date(url: str) -> date | None:
    """The date in an archived SmPC's file name: ``h117810_smpc_20221202_v0005.pdf`` → 2022-12-02."""
    m = _ARCHIVE_DATE.search(url or "")
    try:
        return date(*(int(g) for g in m.groups())) if m else None
    except ValueError:
        return None


def read_smpc(ctx, url: str, label: str, *, archived: bool = False) -> tuple[dict[str, str], str | None]:
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"CBG {label}: HTTP {f.status}{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    if archived:
        text = ARCHIVE_STAMP.sub("", text)
    sections = eu_label_sections(text)
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"CBG {label}: section {', '.join(missing)} not found")
    return sections, f.sha256


def snapshot(ctx, product: dict) -> Snapshot | None:
    extra = product.get("extra") or {}
    url = extra.get("smpc")
    if not url:
        return None
    sections, sha = read_smpc(ctx, url, product["national_id"])
    doc_date = None
    if extra.get("smpc_date"):
        doc_date = date.fromisoformat(extra["smpc_date"])
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url, original_sha256=sha)
