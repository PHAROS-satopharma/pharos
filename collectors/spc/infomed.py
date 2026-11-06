"""PHAROS — Portugal, INFARMED Infomed: the RCM (SmPC) of each authorised medicine.

Source ``spc-infomed``; country PT; Portuguese. Read from GitHub on 6 Nov 2026 and locally on 7 Nov 2026.

Infomed is a JSF (PrimeFaces) site: the search needs the session cookie and the page's ``javax.faces.ViewState``
token, nothing else (no sign-in, no terms, no JavaScript run):

* ``GET /INFOMED-fo/`` gives the session, the form's address and the token;
* the search button is a JSF AJAX post of ``mainForm`` (``mainForm:acMinLength_input=<word>``, the "authorised
  and marketed" box ticked), answered with a redirect to ``pesquisa-avancada.xhtml``, whose table shows the
  first 10 rows and "A mostrar 1 - 10 de um total de 117 registos" (paracetamol 117, ivabradina 17;
  combinations included: "Ibuprofeno + Paracetamol");
* the next pages are the table's own AJAX paging (``mainForm:dt-medicamentos_first=10``…; asking for more than
  10 rows at once is refused with an error page).

Each row: the medicine id (hidden), name, DCI ("Ibuprofeno + Paracetamol"), form, strength, holder. The RCM is
``download-ficheiro.xhtml?med_id=<id>&tipo_doc=rcm`` (a PDF, no session needed), split by QRD section number
(``split_numbered`` per SmPC; 4.1–4.9 watched, 10 recorded) once INFARMED's page stamp ("APROVADO EM 29-06-2022
INFARMED") is taken out; dated by section 10 ("Data da revisão do texto"), else by the stamp, else not (some
RCMs leave section 10 empty). A PDF whose text layer lost a heading number (Ivabradina Teva: "Efeitos
indesejáveis" without its "4.8") is reported unread with the missing section, never guessed.

Portuguese names come from ``ingredient_term`` (lang ``pt``); without one, the English INN is turned into its
Portuguese form by the INN endings ("ivabradine" → "ivabradina", "guaifenesin" → "guaifenesina").
"""

from __future__ import annotations

import html
import re

from collectors.parsers.base import parse_date
from collectors.spc.bdpm import fold
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, label_date, terms_for
from collectors.spc.sections import eu_label_sections, missing_core

SOURCE_ID = "spc-infomed"
COUNTRY = "PT"
LANG = "pt"
BASE = "https://extranet.infarmed.pt"
START = BASE + "/INFOMED-fo/"
RESULTS = BASE + "/INFOMED-fo/pesquisa-avancada.xhtml"
RCM = BASE + "/INFOMED-fo/download-ficheiro.xhtml?med_id={id}&tipo_doc=rcm"
TABLE = "mainForm:dt-medicamentos"
ROWS = 10
MAX_PAGES = 60
AJAX = {"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest"}

_ENDINGS = (("ine", "ina"), ("ate", "ato"), ("ium", "io"), ("one", "ona"), ("ide", "ida"), ("in", "ina"))

_ACTION = re.compile(r'<form id="mainForm"[^>]*action="([^"]+)"')
_STATE = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"')
_TOTAL = re.compile(r"A mostrar \d+ - \d+ de um total de (\d+) registos")
_ONE = re.compile(r"A mostrar \d+ de um total de (\d+) registos")
_ROW = re.compile(r'<tr data-ri="\d+".*?</tr>', re.S)
_CELL = re.compile(r'<td role="gridcell"[^>]*>(.*?)</td>(?=<td|</tr>)', re.S)
_REDIRECT = re.compile(r'<redirect url="([^"]+)"')
# INFARMED's approval stamp, on every page of some RCMs: "APROVADO EM / 29-06-2022 / INFARMED".
_APPROVED = re.compile(r"^[ \t\f]*APROVADO EM[ \t\r]*\n[ \t]*(\d{2}-\d{2}-\d{4})?[ \t\r]*\n?[ \t]*INFARMED[ \t\r]*$", re.M)


def portuguese_inn(en: str) -> str:
    word = en.strip().lower()
    for end, pt in _ENDINGS:
        if word.endswith(end):
            return word[: -len(end)] + pt
    return word


def search_terms(ingredient: dict) -> list[str]:
    terms = terms_for(ingredient, "pt", fallback_en=False)[:2]
    if not terms and ingredient.get("inn_en"):
        terms = [portuguese_inn(ingredient["inn_en"])]
    return terms


def _text(cell: str) -> str:
    cell = re.sub(r"<script.*?</script>|<div class=\"ui-tooltip[^\"]*\"[^>]*>.*?</div></div>", " ", cell, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cell))).strip()


def parse_rows(page: str) -> list[dict]:
    """The table rows of a results page or an AJAX page: ``{"id", "name", "dci", "form", "strength", "holder"}``."""
    out = []
    for tr in _ROW.findall(page):
        cells = [_text(c) for c in _CELL.findall(tr)]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        name = re.sub(r"\s+MG$", "", cells[1]).strip()          # "MG": the generic mark after the name
        out.append({"id": cells[0], "name": name, "dci": cells[2], "form": cells[3], "strength": cells[4],
                    "holder": cells[5], "generic": cells[1].endswith(" MG")})
    return out


def total_of(page: str) -> int | None:
    m = _TOTAL.search(page) or _ONE.search(page)
    return int(m.group(1)) if m else None


def holds(dci: str, term: str) -> bool:
    word = re.compile(rf"(?<![a-z]){re.escape(fold(term))}(?![a-z])")
    return any(word.search(fold(part)) for part in dci.split("+"))


def _get(ctx, url: str):
    if hasattr(ctx, "forget"):
        ctx.forget(url)
    return ctx.get(url, raise_for_status=False)


def _search(ctx, term: str, n: int, gaps: list[str]) -> list[dict]:
    start = _get(ctx, START)
    action, state = _ACTION.search(start.text or ""), _STATE.search(start.text or "")
    if start.status != 200 or not action or not state:
        gaps.append(f"term {n}: start page HTTP {start.status}{'' if action and state else ', no search form'}")
        return []
    r = ctx.post(BASE + html.unescape(action.group(1)), headers=AJAX, accept="application/xml", raise_for_status=False,
                 data={"javax.faces.partial.ajax": "true", "javax.faces.source": "mainForm:ajax",
                       "javax.faces.partial.execute": "@all",
                       "javax.faces.partial.render": "mainForm:messages mainForm:nomesMessage",
                       "mainForm:ajax": "mainForm:ajax", "mainForm": "mainForm",
                       "mainForm:acMinLength_input": term, "mainForm:acMinLength_hinput": term,
                       "mainForm:chkAutorizadoComercializado_input": "on", "javax.faces.ViewState": state.group(1)})
    target = _REDIRECT.search(r.text or "") if r.status == 200 else None
    if not target or "pesquisa-avancada" not in target.group(1):
        if r.status == 200 and "pesquisa-avancada" not in (r.text or "") and "redirect" not in (r.text or ""):
            return []                                        # no medicine of that name: the form answers itself
        gaps.append(f"term {n}: search HTTP {r.status}{', no results page' if r.status == 200 else ''}")
        return []
    first = _get(ctx, RESULTS)
    state = _STATE.search(first.text or "")
    total = total_of(first.text or "")
    if first.status != 200 or total is None or not state:
        gaps.append(f"term {n} page 1: HTTP {first.status}{'' if total is not None else ', no result count'}")
        return []
    rows = parse_rows(first.text)
    for page in range(1, MAX_PAGES):
        if len(rows) >= total:
            return rows
        p = ctx.post(RESULTS, headers=AJAX, accept="application/xml", raise_for_status=False,
                     data={"javax.faces.partial.ajax": "true", "javax.faces.source": TABLE,
                           "javax.faces.partial.execute": TABLE, "javax.faces.partial.render": TABLE,
                           f"{TABLE}_pagination": "true", f"{TABLE}_first": str(page * ROWS),
                           f"{TABLE}_rows": str(ROWS), f"{TABLE}_skipChildren": "true",
                           f"{TABLE}_encodeFeature": "true", "mainForm": "mainForm",
                           "javax.faces.ViewState": state.group(1)})
        got = parse_rows(p.text or "") if p.status == 200 else []
        if not got:
            gaps.append(f"term {n} page {page + 1}: HTTP {p.status}, {len(rows)} of {total} read")
            return rows
        rows += got
    if len(rows) < total:
        gaps.append(f"term {n}: more than {MAX_PAGES} pages")
    return rows


def discover(ctx, ingredient: dict) -> Listing:
    found: dict[str, Product] = {}
    gaps: list[str] = []
    for n, term in enumerate(search_terms(ingredient), start=1):
        for r in _search(ctx, term, n, gaps):
            if holds(r["dci"], term) and r["id"] not in found:
                found[r["id"]] = Product(
                    national_id=r["id"], product_name=f"{r['name']} {r['strength']}".strip(), mah=r["holder"] or None,
                    url=RCM.format(id=r["id"]), country_code=COUNTRY,
                    extra={"rcm": RCM.format(id=r["id"]), "dci": r["dci"], "form": r["form"],
                           "strength": r["strength"], "generic": r["generic"]})
    return Listing(found.values(), gaps=gaps)




def snapshot(ctx, product: dict) -> Snapshot | None:
    url = (product.get("extra") or {}).get("rcm") or RCM.format(id=product["national_id"])
    f = fetch_label(ctx, url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        raise SnapshotError(f"Infomed {product['national_id']} RCM: HTTP {f.status}"
                            f"{'' if f.status != 200 else ', not a PDF'}")
    from collectors.pdf import extract_text

    text, _method, _words = extract_text(f.content, LANG)
    stamp = next((m.group(1) for m in _APPROVED.finditer(text) if m.group(1)), None)
    sections = eu_label_sections(_APPROVED.sub("", text))
    missing = missing_core(sections)
    if missing:
        raise SnapshotError(f"Infomed {product['national_id']} RCM: section {', '.join(missing)} not found")
    doc_date = label_date(sections.get("10")) or (parse_date(stamp) if stamp else None)
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=url, original_sha256=f.sha256)
