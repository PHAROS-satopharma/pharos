"""PHAROS — Korea, MFDS 의약품안전나라 (nedrug.mfds.go.kr): 사용상의주의사항, 효능효과 and 용법용량 per product.

Source ``spc-nedrug``; country KR; Korean. Her list names health.kr for Korea, which needs JavaScript; nedrug is
the regulator's own database and answers plain requests (read from GitHub on 6 Nov 2026, run 42296657165).
Checked 6 Nov 2026 with ivabradine (Procoralan 5 and 7.5 mg) and acetaminophen (1,069 products):

* products: ``/searchDrug?searchYn=true&ingrEngName=<English INN>&cancelCode=0&sort=ITEM_SEQ&sortOrder=ASC
  &page=<n>``: products not cancelled, 15 a page, in a stable order, with "총 <strong>N</strong> 건" at the top.
  Each row of ``table.dr_table2`` labels its cells (``<span class="s-th">품목기준코드</span><span>…</span>``):
  the item code (품목기준코드, the national id), the product name, its English name, the company, the permit
  date, the English names of the main ingredients (주성분영문명, never cut short), prescription or not, ATC.
  The search matches inside words ("ibuprofen" finds dexibuprofen), so a row is kept only when one of its main
  ingredients names the term as a whole word. A page that does not answer, or answers no rows before the count
  is reached, is a gap: the list is partial and nothing is switched off (``common.Listing``).
* label: ``/pbp/cmn/xml/drb/<item code>/NB`` (사용상의주의사항, precautions for use), ``EE`` (효능효과,
  indications) and ``UD`` (용법용량, dosage), each ``<DOC><SECTION><ARTICLE title="3. 이상반응"><PARAGRAPH>
  <![CDATA[…]]>``. The precautions come from the change history instead
  (``/pbp/CCBBB01/getItemChangeHistList?itemSeq=<item code>&docType=NB&page=1``): each row's ``data-docdata`` is
  that version's XML and its date (변경일자) is the revision date. Its newest version is the label as published
  (the same text as the ``NB`` XML, 6 Nov 2026), so one request gives the text and its date; a product without
  history rows is read from the ``NB`` XML, with no date.

Section keys are ``"kr:…"``, from the article's heading words, never its number (the old format numbers
contraindications 1, the new one 2, after 1. 경고): ``kr:warning``, ``kr:contraindications``,
``kr:careful_use``, ``kr:adverse_reactions``, ``kr:general_precautions``, ``kr:interactions``,
``kr:pregnancy`` … (``sections.KR_HEADINGS``); a heading not known is ``kr:other``. ``kr:indications`` and
``kr:dosage`` are the EE and UD documents.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date
from urllib.parse import quote

from collectors.core.context import ParseError
from collectors.parsers.base import soup
from collectors.spc.common import Listing, Product, Snapshot, SnapshotError, fetch_label, terms_for
from collectors.spc.sections import kr_key

SOURCE_ID = "spc-nedrug"
COUNTRY = "KR"
LANG = "ko"
BASE = "https://nedrug.mfds.go.kr"
SEARCH = (BASE + "/searchDrug?searchYn=true&ingrEngName={term}&cancelCode=0&sort=ITEM_SEQ&sortOrder=ASC"
          "&page={page}")
DETAIL = BASE + "/pbp/CCBBB01/getItemDetail?itemSeq={seq}"
DOC_XML = BASE + "/pbp/cmn/xml/drb/{seq}/{doc}"
HISTORY = BASE + "/pbp/CCBBB01/getItemChangeHistList?itemSeq={seq}&docType={doc}&page=1"
MAX_PAGES = 200              # 3,000 products for one term; acetaminophen has 72 pages

_TOTAL = re.compile(r"총\s*<strong>\s*([\d,]+)\s*</strong>\s*건")
_HIST_ROW = re.compile(r'data-docdata="([^"]*)"[^>]*onclick="detailHist\(&#39;\d+&#39;,\s*&#39;(\d{4}-\d{2}-\d{2})&#39;')


def _cells(tr) -> dict[str, str]:
    out: dict[str, str] = {}
    for td in tr.find_all("td"):
        label = td.find("span", class_="s-th")
        if not label:
            continue
        key = label.get_text(strip=True)
        value = " ".join(s.get_text(" ", strip=True) for s in td.find_all("span") if s is not label)
        out[key] = re.sub(r"\s+", " ", value).strip()
    return out


def total_count(text: str) -> int | None:
    m = _TOTAL.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def names_term(main_ingredients_en: str, term: str) -> bool:
    """One of the row's main ingredients (``A/B/C``) holds ``term`` as a whole word; an empty cell is kept."""
    if not main_ingredients_en.strip():
        return True
    word = re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.I)
    return any(word.search(part) for part in main_ingredients_en.split("/"))


def parse_search(page) -> list[dict]:
    """The rows of one result page, each as ``{label: value}`` plus ``"seq"``."""
    table = soup(page).find("table", class_="dr_table2")
    if table is None or table.tbody is None:
        return []
    rows = []
    for tr in table.tbody.find_all("tr", recursive=False):
        cells = _cells(tr)
        seq = cells.get("품목기준코드", "")
        if seq.isdigit():
            rows.append(cells | {"seq": seq})
    return rows


def product_from(row: dict) -> Product:
    return Product(
        national_id=row["seq"], product_name=row.get("제품명") or row["seq"],
        mah=row.get("업체명") or None, url=DETAIL.format(seq=row["seq"]), country_code=COUNTRY,
        extra={"name_en": row.get("제품영문명") or None, "mah_en": row.get("업체명(영문)") or None,
               "main_ingredients_en": row.get("주성분영문명") or None, "permit_date": row.get("허가일") or None,
               "atc": row.get("ATC코드") or None, "rx": row.get("전문의약품") or None})


def discover(ctx, ingredient: dict) -> Listing:
    found: dict[str, Product] = {}
    gaps: list[str] = []
    for n, term in enumerate(terms_for(ingredient, "en")[:3], start=1):
        seen = 0
        for page in range(1, MAX_PAGES + 1):
            f = ctx.get(SEARCH.format(term=quote(term), page=page))
            if f.status != 200:
                gaps.append(f"term {n} page {page}: HTTP {f.status}")
                break
            text = f.text
            total = total_count(text)
            if total is None:
                gaps.append(f"term {n} page {page}: no result count")
                break
            rows = parse_search(text)
            seen += len(rows)
            for r in rows:
                if names_term(r.get("주성분영문명", ""), term):
                    found.setdefault(r["seq"], product_from(r))
            if seen >= total:
                break
            if not rows:
                gaps.append(f"term {n} page {page}: no rows, {seen} of {total} read")
                break
        else:
            gaps.append(f"term {n}: more than {MAX_PAGES} pages")
    return Listing(found.values(), gaps=gaps)


def _plain(fragment: str) -> str:
    if "<" in fragment:
        fragment = soup(f"<div>{fragment}</div>").get_text("\n")
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(fragment)).strip()


def doc_sections(xml: bytes | str, doc: str) -> dict[str, str]:
    """``{"kr:…": text}`` of one nedrug document (NB, EE or UD); empty when it holds no text."""
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    if not raw.strip():
        return {}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ParseError(f"nedrug {doc}: not XML ({exc})") from None
    out: dict[str, list[str]] = {}
    for section in root.iter("SECTION"):
        for article in section.iter("ARTICLE"):
            title = (article.get("title") or "").strip() or (section.get("title") or "").strip()
            body = "\n".join(t for t in (_plain(p.text or "") for p in article.iter("PARAGRAPH")) if t)
            if not body and not title:
                continue
            key = {"EE": "kr:indications", "UD": "kr:dosage"}.get(doc) or kr_key(title)
            out.setdefault(key, []).append("\n".join(x for x in (title, body) if x))
    return {k: "\n\n".join(v) for k, v in out.items()}


def latest_history(text: str) -> tuple[str, date] | None:
    """The newest version in a change-history page: its XML and its date; None when the page lists none."""
    rows = [(html.unescape(x), d) for x, d in _HIST_ROW.findall(text)]
    if not rows:
        return None
    xml, day = max(rows, key=lambda r: r[1])
    return xml, date.fromisoformat(day)


def snapshot(ctx, product: dict) -> Snapshot | None:
    seq = product["national_id"]
    sections: dict[str, str] = {}
    doc_date = None
    h = fetch_label(ctx, HISTORY.format(seq=seq, doc="NB"))
    newest = latest_history(h.text) if h.status == 200 else None
    if newest:
        sections.update(doc_sections(newest[0], "NB"))
        doc_date = newest[1]
    for doc in (("EE", "UD") if newest else ("NB", "EE", "UD")):
        f = fetch_label(ctx, DOC_XML.format(seq=seq, doc=doc))
        if f.status != 200:
            raise SnapshotError(f"nedrug {seq} {doc}: HTTP {f.status}")
        sections.update(doc_sections(f.content, doc))
    if not sections:
        return None
    return Snapshot(sections=sections, doc_date=doc_date, lang=LANG, source_url=DETAIL.format(seq=seq))
