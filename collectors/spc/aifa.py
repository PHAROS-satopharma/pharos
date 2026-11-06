"""PHAROS — Italy, AIFA drug database (Banca Dati Farmaci): the RCP of each authorised medicine.

Source ``spc-aifa``; country IT; Italian. Read from GitHub and locally on 6–7 Nov 2026:

* search: ``https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/formadosaggio/ricerca?query=<word>&page=<n>`` (JSON,
  10 a page, ``totalPages`` and ``totalElements``), one row per strength and form: ``principiAttiviIt``
  (Italian INNs, salts as separate words: "OSSICODONE CLORIDRATO"), ``medicinale`` (``codiceMedicinale``,
  ``aic6``, ``codiceSis`` the holder's code, ``denominazioneMedicinale``, ``aziendaTitolare``,
  ``statoAmministrativo`` "A" authorised), ``codiceAtc``. The query matches whole Italian words only
  ("ivabradine" and "ivabradin" find nothing, "ivabradina" 25 rows, 12 medicines; "paracetamolo" 203 rows,
  122 medicines, combinations included).
* label: ``…/organizzazione/<codiceSis>/farmaci/<aic6>/stampati?ts=RCP`` (a PDF, served as
  ``application/octet-stream``; one RCP per medicine, all strengths), split by QRD section number
  (``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded) once AIFA's page footer and margin stamp are taken out
  (``clean``). The API gives no RCP date; the footer's "Documento reso disponibile da AIFA il 20/05/2023" is
  the label's date, and the label's hash says whether it changed.

Italian names come from ``ingredient_term`` (lang ``it``); without one, the English INN is turned into its
Italian form by the INN endings ("ivabradine" → "ivabradina", "paracetamol" → "paracetamolo").
"""

from __future__ import annotations

import re
from urllib.parse import quote

from collectors.parsers.base import parse_date
from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_date, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-aifa"
COUNTRY = "IT"
LANG = "it"
API = "https://api.aifa.gov.it/aifa-bdf-eif-be/1.0.0/"
SEARCH = API + "formadosaggio/ricerca?query={term}&page={page}"
RCP = API + "organizzazione/{sis}/farmaci/{aic6}/stampati?ts=RCP"
MAX_PAGES = 60                               # paracetamolo: 21

# English INN ending → Italian (the INN rules; the longest ending first).
_ENDINGS = (("ine", "ina"), ("ate", "ato"), ("ium", "io"), ("ol", "olo"), ("in", "ina"), ("an", "ano"),
            ("il", "ile"), ("one", "one"), ("ide", "ide"), ("am", "am"))


def italian_inn(en: str) -> str:
    """"ivabradine" → "ivabradina", "carvedilol" → "carvedilolo", "guaifenesin" → "guaifenesina"."""
    word = en.strip().lower()
    for end, it in _ENDINGS:
        if word.endswith(end):
            return word[: -len(end)] + it
    return word


def search_terms(ingredient: dict) -> list[str]:
    terms = terms_for(ingredient, "it", fallback_en=False)[:3]
    if not terms and ingredient.get("inn_en"):
        terms = [italian_inn(ingredient["inn_en"])]
    return terms


def holds(principles: list[str], term: str) -> bool:
    word = re.compile(rf"(?<![a-z]){re.escape(fold(term))}(?![a-z])")
    return any(word.search(fold(p)) for p in principles)


def rcp_url(medicine: dict) -> str:
    return RCP.format(sis=medicine["codiceSis"], aic6=f"{int(medicine['aic6']):06d}")


def products_from(rows: list[dict], term: str) -> dict[str, Product]:
    out: dict[str, Product] = {}
    for r in rows:
        m = r.get("medicinale") or {}
        if m.get("statoAmministrativo") != "A" or r.get("revocato") or not holds(r.get("principiAttiviIt") or [], term):
            continue
        if m.get("aic6") is None or m.get("codiceSis") is None:
            continue
        aic6 = f"{int(m['aic6']):06d}"
        p = out.get(aic6)
        if p is None:
            url = rcp_url(m)
            p = out[aic6] = Product(
                national_id=aic6, product_name=(m.get("denominazioneMedicinale") or aic6).strip(),
                mah=m.get("aziendaTitolare") or None, url=url, country_code=COUNTRY,
                extra={"rcp": url, "medicine": m.get("codiceMedicinale"), "atc": (r.get("codiceAtc") or [None])[0],
                       "ingredients": r.get("principiAttiviIt") or [], "forms": []})
        form = r.get("descrizioneFormaDosaggio")
        if form and form not in p.extra["forms"]:
            p.extra["forms"].append(form)
    return out


def discover(ctx, ingredient: dict) -> Listing:
    found: dict[str, Product] = {}
    gaps: list[str] = []
    for n, term in enumerate(search_terms(ingredient), start=1):
        page, pages = 0, 1
        while page < pages:
            if page >= MAX_PAGES:
                gaps.append(f"term {n}: more than {MAX_PAGES} pages")
                break
            f = ctx.get(SEARCH.format(term=quote(term), page=page), accept="application/json")
            if f.status != 200:
                gaps.append(f"term {n} page {page + 1}: HTTP {f.status}")
                break
            try:
                data = f.json()["data"]
                pages = int(data["totalPages"])
                rows = data["content"]
            except (ValueError, KeyError, TypeError):
                gaps.append(f"term {n} page {page + 1}: not the search answer")
                break
            for aic6, p in products_from(rows, term).items():
                if aic6 in found:
                    found[aic6].extra["forms"] += [x for x in p.extra["forms"] if x not in found[aic6].extra["forms"]]
                else:
                    found[aic6] = p
            page += 1
    return Listing(found.values(), gaps=gaps)



# Every page of an AIFA RCP ends with the date AIFA published it and a disclaimer, and carries "Agenzia
# Italiana del Farmaco" down its right margin, which the text layer breaks into pieces at the end of lines
# ("…epatica. È necessario      Italiana d") and sometimes in front of a heading ("     Italiana d4.8 Effetti").
_FOOTER = re.compile(r"(?:^[ \t]*\d{1,3}[ \t\r]*\n(?:[ \t\r]*\n)*)?"
                     r"[ \t]*Documento reso disponibile da AIFA il (\d{2}/\d{2}/\d{4})[ \t\r]*\n(?:[ \t\r]*\n)*"
                     r"[ \t]*Esula dalla competenza(?:[^\n]*\n){0,4}?[^\n]*\(o titolare AIC\)\.?[ \t\r]*$", re.M)
_STAMP = "Agenzia Italiana del Farmaco"
_TAIL = re.compile(r"[ \t]{5,}(\S[^\t]{0,19}?)[ \t]*$")


def published(text: str):
    """The date AIFA published this RCP ("Documento reso disponibile da AIFA il 20/05/2023")."""
    m = _FOOTER.search(text)
    return parse_date(m.group(1)) if m else None


def clean(text: str) -> str:
    """The RCP without AIFA's page footers and margin stamp, so neither splits a heading nor reads as a change."""
    text = _FOOTER.sub("", text)
    lines = text.splitlines()
    pieces = set()
    for i, line in enumerate(lines):
        m = _TAIL.search(line)
        if m and m.group(1).strip() in _STAMP:
            pieces.add(m.group(1).strip())
            lines[i] = line[: m.start()]
        elif line.strip() and line.strip() in _STAMP and len(line.strip()) >= 3:
            lines[i] = ""
    # A piece seen at a line's end is also stripped where it sits in front of a line's text, or glued to its
    # end ("…compresse rivestite con filmel Farm"); a piece after a space ("della Agenzia") is the text's own.
    known = sorted((p for p in pieces if len(p) >= 3), key=len, reverse=True)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        for p in known:
            if (stripped.startswith(p) and len(line) - len(stripped) >= 3 and len(stripped) > len(p)
                    and (not stripped[len(p)].isspace() or stripped[len(p):len(p) + 2] == "  "
                         or p not in _STAMP.split())):
                line = lines[i] = stripped[len(p):]
                break
        for p in known:
            if len(p) >= 5 and line.endswith(p) and len(line) > len(p) and not line[-len(p) - 1].isspace():
                lines[i] = line[: -len(p)]
                break
    return "\n".join(lines)



def snapshot(ctx, product: dict) -> Snapshot | None:
    url = (product.get("extra") or {}).get("rcp") or product.get("url")
    if not url:
        return None
    f = fetch_label(ctx, url, accept="application/pdf,*/*;q=0.5")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"AIFA {product['national_id']} RCP: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    sections = eu_label_sections(clean(text))
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"AIFA {product['national_id']} RCP: section {', '.join(missing)} not found")
    return Snapshot(sections=sections, doc_date=published(text) or label_date(sections.get("10")), lang=LANG,
                    source_url=url,
                    original_sha256=f.sha256)
