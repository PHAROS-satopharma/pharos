"""PHAROS — Japan, PMDA 医療用医薬品 添付文書 (package inserts).

Source ``spc-pmda``; country JP; Japanese, kept as published.

* Discovery: PMDA's per-ingredient page ``https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/<code>``
  (``<code>`` = the 7-character 一般名 code, e.g. 2190417), checked 4 Nov 2026 (fixture
  ``tests/fixtures/spc-pmda/general_list_2190417.html``). Its product table has one ``tr`` per
  product: 販売名 | 製造販売業者等 | 添付文書 (``a[href="../ResultDataSetPDF/<package id>"]``
  "PDF(2026年10月27日)" — the revision date — and an HTML view) | IF | RMP …
  The codes for an ingredient come from (1) its ``code`` terms for Japan on the Ingredients page
  (country JP: the 7-character 一般名 code, or a 12-character YJ code whose first 7 characters are
  it; lornoxicam = 1149036, ロルカム錠 and ロルノキシカム錠「KO」), (2) the ``general_list`` links
  PHAROS already stored from ``pmda-revisions`` documents matched to the ingredient, and (3) the
  environment variable ``SPC_PMDA_GENERAL_CODES`` (``inn_en=code,code;inn_en=code``). Without
  any of them Japan watches nothing for that ingredient. The package id ``<company>_<YJ code>_<version>`` minus its version suffix is the
  national id, so a new revision of the same insert is the same product.
* Snapshot: the PDF ``https://www.pmda.go.jp/PmdaSearch/iyakuDetail/ResultDataSetPDF/<package id>``,
  text by ``collectors.pdf.extract_text_by_columns`` (``jpn`` OCR fallback), split by 添付文書 heading
  (``sections.split_japanese``: 1. 警告, 2. 禁忌, 8. 重要な基本的注意, 9. 特定の背景…, 10. 相互作用,
  11. 副作用, 13. 過量投与). The inserts are printed in two columns; read straight across, a
  right-column heading sat inside a left-column line and sections 3–8 were lost (fixture
  ``tests/fixtures/spc-pmda/insert_870276_2190417A1029_2_04.pdf``). ``Snapshot.method`` says how
  the text was read — ``COLUMNS`` (column by column) or ``LAYOUT`` (straight across, when
  ``pdftotext -bbox`` is unavailable) — so a snapshot is diffed only against one read the same
  way, and the snapshots stored before (no method) are never compared with the new reading: the
  first read after the change is a new baseline, not a label change.
"""

from __future__ import annotations

import os
import re

from collectors.parsers._html_util import absolute, local_date, node_text
from collectors.parsers.base import soup
from collectors.spc.common import Product, Snapshot
from collectors.spc.sections import split_japanese

SOURCE_ID = "spc-pmda"
COUNTRY = "JP"
LANG = "ja"
GENERAL = "https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/{code}"
PDF = "https://www.pmda.go.jp/PmdaSearch/iyakuDetail/ResultDataSetPDF/{pid}"
_PID = re.compile(r"ResultDataSetPDF/([0-9A-Za-z_]+)")
_CODE = re.compile(r"/GeneralList/([0-9A-Za-z]+)")
_VERSION = re.compile(r"^(.+?_[0-9A-Z]+)_\d+_\d+$")
COLUMNS = "pdf-columns-1"    # Snapshot.method: two-column pages read column by column
LAYOUT = "pdf-layout-2"      # Snapshot.method: read straight across (no word boxes on the runner)

SQL_CODES = """select distinct d.structured -> 'general_list' as links
                 from document d join match m on m.document_id = d.id
                where d.source_id = 'pmda-revisions' and m.ingredient_id = %(iid)s
                  and d.structured ? 'general_list'"""

SQL_TERM_CODES = """select term from ingredient_term
                     where ingredient_id = %(iid)s and kind = 'code' and country_code = 'JP'
                     order by term"""
_GENERAL_CODE = re.compile(r"^([0-9]{4}[0-9A-Z]{3})(?:[0-9A-Z]{5})?$")


def stable_id(pid: str) -> str:
    m = _VERSION.match(pid)
    return m.group(1) if m else pid


def env_codes(inn_en: str) -> list[str]:
    raw = os.environ.get("SPC_PMDA_GENERAL_CODES", "")
    for part in raw.split(";"):
        name, _, codes = part.partition("=")
        if name.strip().casefold() == (inn_en or "").casefold():
            return [c.strip() for c in codes.split(",") if c.strip()]
    return []


def general_codes(ctx, ingredient: dict) -> list[str]:
    codes: list[str] = []
    db = getattr(ctx, "db", None)
    if db is not None and ingredient.get("id"):
        for row in db.fetchall(SQL_TERM_CODES, {"iid": ingredient["id"]}):
            m = _GENERAL_CODE.match(str(row.get("term") or "").strip().upper())
            if m and m.group(1) not in codes:
                codes.append(m.group(1))
        for row in db.fetchall(SQL_CODES, {"iid": ingredient["id"]}):
            for link in row.get("links") or []:
                m = _CODE.search(str(link))
                if m and m.group(1) not in codes:
                    codes.append(m.group(1))
    for c in env_codes(ingredient.get("inn_en") or ""):
        if c not in codes:
            codes.append(c)
    return codes


def parse_general_list(html, base_url: str) -> list[Product]:
    doc = soup(html)
    out: list[Product] = []
    seen: set[str] = set()
    for tr in doc.select("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3:
            continue
        a = tr.select_one("a[href*='ResultDataSetPDF/']")
        if a is None:
            continue
        m = _PID.search(a["href"])
        if not m:
            continue
        pid = m.group(1)
        nid = stable_id(pid)
        if nid in seen:
            continue
        seen.add(nid)
        out.append(Product(
            national_id=nid, product_name=node_text(tds[0]), mah=node_text(tds[1]) or None,
            url=absolute(a["href"], base_url), country_code=COUNTRY,
            extra={"package_id": pid, "pdf_date": str(local_date(node_text(a), "ja") or "")
                   or None}))
    return out


def discover(ctx, ingredient: dict) -> list[Product]:
    found: dict[str, Product] = {}
    for code in general_codes(ctx, ingredient):
        f = ctx.get(GENERAL.format(code=code))
        if f.status != 200:
            continue
        for p in parse_general_list(f, f.final_url):
            found.setdefault(p.national_id, p)
    return list(found.values())


def snapshot(ctx, product: dict) -> Snapshot | None:
    extra = product.get("extra") or {}
    url = PDF.format(pid=extra["package_id"]) if extra.get("package_id") else product.get("url")
    if not url:
        return None
    f = ctx.get(url, accept="application/pdf")
    if f.status != 200 or not f.is_pdf:
        return None
    from collectors.pdf import extract_text_by_columns

    text, _m, _w, by_columns = extract_text_by_columns(f.content, LANG)
    sections = split_japanese(text)
    if not sections:
        return None
    when = local_date(extra.get("pdf_date") or "", "ja")
    return Snapshot(sections=sections, doc_date=when, lang=LANG, source_url=url,
                    original_sha256=f.sha256, method=COLUMNS if by_columns else LAYOUT)
