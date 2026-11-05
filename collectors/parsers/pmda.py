"""PHAROS — PMDA (Japan): 使用上の注意の改訂指示, 緊急安全性情報・安全性速報, PMDA医療安全情報.

Three sources share this module; ``options.page`` (or the source id) says which page it is. Titles
stay in Japanese exactly as published. Pages are UTF-8 today; ``Fetched.text`` also handles
Shift_JIS should PMDA switch back.

``page: revisions`` — ``pmda-revisions``; ``source.url`` is the index
``https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/revision-of-precautions/0001.html``,
whose links "2026年度指示分" (→ ``0375.html``), "2025年度指示分" (→ ``0374.html``) … lead to one page
per fiscal year. The newest year is read (a backfill reads ``backfill_years``, default 2). Each year
page has ``table.normal-table`` with th 発出年月日 | 一般的名称 | 改訂内容 | 調査結果, where the
date cell spans several rows (``rowspan``): "2026年10月27日" + the MHLW notice PDF
(医薬安発1027第1号). Every following row is one ingredient: 一般的名称 links
(``/PmdaSearch/iyakuDetail/GeneralList/<code>``), the 改訂内容 PDF (``/files/<n>.pdf``) and the
調査結果 report PDF (which may itself span rows). One item per ingredient row; the item URL is its
改訂内容 PDF; attachments are that PDF, the notice and the report. doc_type ``safety_update``
(``options.doc_type`` overrides).

``page: urgent`` — ``pmda-urgent``,
``https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/esc-rsc/0001.html``. Table
年月日 | company in ``strong`` + letter PDFs (the first one is the title; the size marker
"[604.53KB]" is removed) | MHLW press PDFs. Background ``rgb(224, 255, 255)`` (blue) is a 安全性速報
(ブルーレター), yellow is a 緊急安全性情報 (イエローレター). doc_type ``safety_alert``.

``page: msi`` — ``pmda-msi``, ``https://www.pmda.go.jp/safety/info-services/medical-safety-info/0001.html``.
Table No. | 発行年月日 ("2026年4月") | タイトル (first PDF link = the issue) | image. doc_type
``safety_update``.

(checked 4 Nov 2026)

Options: ``page``, ``doc_type``, ``backfill_years`` (2), ``include_keywords`` /
``exclude_keywords``, ``lang`` (``ja``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, clean, keep, links_in, local_date, node_text,
                                           require)
from collectors.parsers.base import Item, ParseError, SourceConfig, soup

_SIZE = re.compile(r"\s*[\[［]\s*[\d.,]+\s*[KMG]?B\s*[\]］]\s*$", re.I)
# Gregorian (2026年10月27日) or era (令和7年10月27日, 令和元年5月) — an era-dated cell is still a date cell.
_JA_DATE = re.compile(r"(?:\d{4}|(?:令和|平成)\s*(?:元|\d{1,2}))\s*年\s*\d{1,2}\s*月"
                      r"(?:\s*\d{1,2}\s*日)?")
_FY = re.compile(r"(\d{4})\s*年度指示分")
_FILE = re.compile(r"/files/(\d+)\.pdf", re.I)
_BLUE = re.compile(r"224\s*,\s*255\s*,\s*255|#e0ffff", re.I)


def page_kind(source: SourceConfig) -> str:
    kind = (source.options or {}).get("page")
    if kind:
        return str(kind).lower()
    for k in ("revisions", "urgent", "msi"):
        if source.id.endswith(k):
            return k
    return "revisions"


def strip_size(text: str) -> str:
    return clean(_SIZE.sub("", clean(text)))


def _file_id(url: str) -> str:
    m = _FILE.search(url)
    return m.group(1) if m else url


# ───────────────────────────── revisions ─────────────────────────────

def fiscal_year_links(html, base_url: str) -> list[tuple[int, str]]:
    """[(fiscal year, url)] newest first, from the revision index page."""
    doc = soup(html)
    out: dict[int, str] = {}
    for a in doc.select("a[href]"):
        m = _FY.search(node_text(a))
        if m:
            out.setdefault(int(m.group(1)), absolute(a["href"], base_url))
    return sorted(out.items(), reverse=True)


def parse_revisions(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "ja"
    doc_type = (source.options or {}).get("doc_type", "safety_update")
    items: list[Item] = []
    seen: set[str] = set()
    for table in doc.select("table.normal-table"):
        cur_date_text, cur_notice = "", []
        report: list[str] = []
        report_left = 0
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue
            first = node_text(tds[0])
            if _JA_DATE.match(first):
                cur_date_text = _JA_DATE.match(first).group(0)
                cur_notice = links_in([tds[0]], base_url)
                tds = tds[1:]
            if not tds:
                continue
            name_cell = tds[0]
            names = [node_text(a) for a in name_cell.select("a[href]")] or [node_text(name_cell)]
            names = [n for n in names if n]
            revision = links_in(tds[1:2], base_url)
            if len(tds) >= 3:
                report = links_in(tds[2:3], base_url)
                report_left = int(tds[2].get("rowspan") or 1) - 1
            elif report_left > 0:
                report_left -= 1
            else:
                report = []
            if not names or not revision:
                continue
            url = revision[0]
            ext = f"pmda-rev:{_file_id(url)}"
            title = " / ".join(names)
            if ext in seen or not keep(source, title):
                continue
            seen.add(ext)
            attachments = [u for u in revision + cur_notice + report if u.lower().endswith(".pdf")]
            items.append(Item(
                external_id=ext, url=url, title=title,
                published=local_date(cur_date_text, lang), doc_type=doc_type, lang=lang,
                body_text=title, attachment_urls=list(dict.fromkeys(attachments)),
                structured={"generic_names": names, "notice_date": cur_date_text,
                            "notice_pdf": cur_notice[0] if cur_notice else None,
                            "general_list": [absolute(a["href"], base_url)
                                             for a in name_cell.select("a[href]")]}))
    return items


# ───────────────────────────── urgent ─────────────────────────────

def parse_urgent(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "ja"
    items: list[Item] = []
    for table in doc.select("table.normal-table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 2 or not _JA_DATE.search(node_text(tds[0])):
                continue
            letters = tds[1].select("a[href]")
            if not letters:
                continue
            url = absolute(letters[0]["href"], base_url)
            title = strip_size(node_text(letters[0]))
            company = node_text(tds[1].select_one("strong"))
            if not title or not keep(source, title, company):
                continue
            style = (tds[0].get("style") or "") + (tr.get("style") or "")
            kind = "安全性速報" if _BLUE.search(style) else "緊急安全性情報"
            attachments = links_in(tds[1:], base_url)
            items.append(Item(
                external_id=f"pmda-urgent:{_file_id(url)}", url=url, title=title,
                published=local_date(node_text(tds[0]), lang), doc_type="safety_alert",
                lang=lang, body_text="\n".join([company] + [strip_size(node_text(a))
                                                             for a in letters]).strip(),
                attachment_urls=attachments,
                structured={"company": company or None, "letter_kind": kind}))
    return items


# ───────────────────────────── medical safety information ─────────────────────────────

def parse_msi(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "ja"
    items: list[Item] = []
    for table in doc.select("table.normal-table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 3:
                continue
            a = tds[2].select_one("a[href]")
            if a is None:
                continue
            url = absolute(a["href"], base_url)
            title = strip_size(node_text(a))
            number = node_text(tds[0])
            if not title or not keep(source, title):
                continue
            items.append(Item(
                external_id=f"pmda-msi:{number or _file_id(url)}", url=url, title=title,
                published=local_date(node_text(tds[1]), lang),
                doc_type=(source.options or {}).get("doc_type", "safety_update"), lang=lang,
                attachment_urls=links_in(tds[2:3], base_url), structured={"number": number}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    kind = page_kind(source)
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    if kind == "urgent":
        items = parse_urgent(f, f.final_url, source)
        require(items or soup(f).select("table.normal-table td a[href]"), f, marker="normal-table")
        return items
    if kind == "msi":
        items = parse_msi(f, f.final_url, source)
        require(items or soup(f).select("table.normal-table td a[href]"), f, marker="normal-table")
        return items
    # revisions: index → fiscal-year pages (or source.url already is a year page)
    years = fiscal_year_links(f, f.final_url)
    if not years:
        items = parse_revisions(f, f.final_url, source)
        if not items and not soup(f).select("table.normal-table"):
            raise ParseError(f"no 年度指示分 links and no revision table at {f.final_url}")
        return items
    n = int((source.options or {}).get("backfill_years", 2)) if ctx.backfill else 1
    out: list[Item] = []
    for i, (_fy, url) in enumerate(years[:n]):
        page = ctx.get(url)
        if page.status == 304:
            continue
        got = parse_revisions(page, page.final_url, source)
        if i == 0:
            require(got or soup(page).select("table.normal-table td a[href]"), page,
                    marker="normal-table")
        out.extend(got)
    return out
