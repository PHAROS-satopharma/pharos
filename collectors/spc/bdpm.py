"""PHAROS — France, Base de données publique des médicaments (BDPM): RCP per section.

Source ``spc-bdpm``; country FR; French.

* Discovery uses the bulk files listed on ``https://base-donnees-publique.medicaments.gouv.fr/telechargement``
  (checked 4 Nov 2026; the old ``telechargement.php?fichier=`` address now answers 404):
  ``/download/file/CIS_COMPO_bdpm.txt`` (compositions, ~2.6 MB) and ``/download/file/CIS_bdpm.txt``
  (specialities, ~3 MB). Both are tab-separated, one row per line:

  - CIS_COMPO: CIS | élément pharmaceutique | code substance | dénomination de la substance |
    dosage | référence du dosage | nature du composant (SA = substance active, FT = fraction
    thérapeutique) | numéro de liaison SA/FT;
  - CIS: CIS | dénomination | forme | voies | statut administratif AMM | type de procédure |
    état de commercialisation | date AMM | statut BdM | numéro d'autorisation européenne |
    titulaire(s) | surveillance renforcée.

  A product is kept when one of its SA/FT substances contains the ingredient's French INN
  (``ingredient_term`` lang ``fr``, e.g. "LORNOXICAM", else the English INN) and its AMM status
  is active. Both sides are compared without accents or case, so "carvedilol" finds "CARVÉDILOL".
  The files are ISO-8859-1/Windows-1252 with no charset header; they are decoded as such. Centrally
  authorised products (an EU number) are left to ``spc-ema-epar`` unless ``include_central``.
* Snapshot: the RCP page (``RCP_URL``, overridable by the ``SPC_BDPM_RCP_URL`` environment
  variable) split by QRD section number. The new BDPM front end is script-driven, so the classic
  ``affichageDoc.php?specid=<CIS>&typedoc=R`` address is used; it could not be confirmed from here
  on 4 Nov 2026 (see the fixture README).
"""

from __future__ import annotations

import os
import unicodedata

from collectors.core.context import FetchError
from collectors.parsers._html_util import block_text
from collectors.parsers.base import soup
from collectors.spc.common import Product, Snapshot, run_cache, terms_for
from collectors.spc.sections import WATCHED_EU, split_numbered

SOURCE_ID = "spc-bdpm"
COUNTRY = "FR"
LANG = "fr"
HOST = "https://base-donnees-publique.medicaments.gouv.fr"
COMPO_URL = HOST + "/download/file/CIS_COMPO_bdpm.txt"
CIS_URL = HOST + "/download/file/CIS_bdpm.txt"
RCP_URL = os.environ.get("SPC_BDPM_RCP_URL", HOST + "/affichageDoc.php?specid={cis}&typedoc=R")

def _decode(content: bytes) -> str:
    """The files are Windows-1252 (É is byte 0xC9); UTF-8 is accepted should the server switch."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def fold(text: str) -> str:
    """Case and accents dropped: "CARVÉDILOL" and "carvedilol" both read "carvedilol"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _rows(ctx, url: str) -> list[list[str]]:
    """The rows of one bulk file, read once per run. A file that does not answer 200 is a failure
    of the source (raised), never an empty file — that would read as "no products" all run."""
    cache = run_cache(ctx, "bdpm")
    if url not in cache:
        f = ctx.get(url, accept="text/plain,*/*;q=0.5")
        if f.status != 200:
            raise FetchError(f.status, url, f"BDPM bulk file {url}: HTTP {f.status}")
        rows = [ln.split("\t") for ln in f.text.splitlines() if ln.strip()]
        if not rows:
            raise FetchError(f.status, url, f"BDPM bulk file {url} is empty")
        cache[url] = rows
    return cache[url]


def match_cis(compo_rows: list[list[str]], terms: list[str]) -> set[str]:
    needles = [n for n in (fold(t) for t in terms) if n]
    out: set[str] = set()
    for r in compo_rows:
        if len(r) < 7:
            continue
        nature = r[6].strip().upper()
        if nature not in ("SA", "FT"):
            continue
        name = fold(r[3])
        if any(n in name for n in needles):
            out.add(r[0].strip())
    return out


def products_from(cis_rows: list[list[str]], wanted: set[str], *,
                  include_central: bool = False) -> list[Product]:
    out: list[Product] = []
    for r in cis_rows:
        if len(r) < 11 or r[0].strip() not in wanted:
            continue
        status = r[4].strip().casefold()
        if "active" not in status:
            continue
        if r[9].strip() and not include_central:
            continue
        cis = r[0].strip()
        out.append(Product(national_id=cis, product_name=r[1].strip(),
                           mah=r[10].strip() or None,
                           url=f"{HOST}/medicament/{cis}/extrait", country_code=COUNTRY,
                           extra={"commercialisation": r[6].strip(), "procedure": r[5].strip()}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    terms = terms_for(ingredient, "fr")
    cis = match_cis(_rows(ctx, COMPO_URL), terms)
    if not cis:
        return []
    return products_from(_rows(ctx, CIS_URL), cis)


def wanted(section: str) -> bool:
    parent = ".".join(section.split(".")[:2])
    return section == "10" or section in WATCHED_EU or parent in WATCHED_EU


def parse_rcp(html) -> dict[str, str]:
    doc = soup(html)
    node = doc.select_one("#textDocument") or doc.select_one("main") or doc.body or doc
    return {k: v for k, v in split_numbered(block_text(node)).items() if wanted(k)}


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = RCP_URL.format(cis=product["national_id"])
    f = ctx.get(url)
    if f.status != 200:
        return None
    sections = parse_rcp(f)
    if not sections:
        return None
    return Snapshot(sections=sections, lang=LANG, source_url=f.final_url,
                    original_sha256=f.sha256)
