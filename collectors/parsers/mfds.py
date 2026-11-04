"""PHAROS — MFDS (Korea) 안전성서한(속보): safety letters and rapid communications, on 의약품안전나라.

Source: ``mfds-letters``; ``source.url``: ``https://nedrug.mfds.go.kr/pbp/CCBAC01``
(the ``m_1067`` board on mfds.go.kr is COVID-only and is not used).

Page structure relied on (checked 4 Nov 2026):

* list: a ``table`` whose ``tbody tr`` rows carry labelled cells (``span.s-th`` + value ``span``):
  제목 (``p.blue_cr a[href="/pbp/CCBAC01/getItem?&safeLetterNo=516"]``), 요약, 담당부서, 조회수,
  공고일 (YYYY-MM-DD). Ten per page, newest first; further pages ``?page=2``.
* detail ``/pbp/CCBAC01/getItem?safeLetterNo=<n>``: ``table.tb_base`` rows 제목, 공개일자, 정보요약,
  상세정보 (``pre.ccc``), 조치사항; attachments are ``span[id^=fileNameTd]`` file names with a
  button ``onclick="downEdmsFile('<docId>')"``; the file itself is served by
  ``https://nedrug.mfds.go.kr/cmn/edms/down/<docId>`` (PDF, sometimes HWP — HWP text extraction is
  a phase-2 item, the original is archived either way).

doc_type: titles with 회수 / 속보 → ``safety_alert``; 서한 → ``dhpc``; otherwise ``safety_alert``.
Many titles are generic ("안전성 서한 배포 알림"), so the 요약 summary is kept as ``body_text``.

Options: ``include_keywords`` / ``exclude_keywords``; ``max_pages`` (1) / ``backfill_pages`` (5);
``lang`` (``ko``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, block_text, fill_detail, keep, local_date,
                                           node_text, pages_to_read, require)
from collectors.parsers.base import Item, SourceConfig, soup

HOST = "https://nedrug.mfds.go.kr"
DOWNLOAD = HOST + "/cmn/edms/down/"
_NO = re.compile(r"safeLetterNo=(\d+)")
_EDMS = re.compile(r"downEdmsFile\(\s*['\"]([^'\"]+)['\"]\s*\)")


def doc_type_for(title: str) -> str:
    if "속보" in title or "회수" in title:
        return "safety_alert"
    if "서한" in title:
        return "dhpc"
    return "safety_alert"


def _cells(tr) -> dict[str, str]:
    out: dict[str, str] = {}
    for td in tr.find_all("td", recursive=False):
        label = td.select_one("span.s-th")
        if label is None:
            continue
        name = node_text(label)
        label.extract()
        out[name] = node_text(td)
    return out


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "ko"
    items: list[Item] = []
    for tr in doc.select("table tbody tr"):
        a = tr.select_one("a[href*='safeLetterNo=']")
        if a is None:
            continue
        m = _NO.search(a["href"])
        if not m:
            continue
        title = node_text(a)
        cells = _cells(tr)
        summary = cells.get("요약", "")
        if not title or not keep(source, title, summary):
            continue
        url = f"{HOST}/pbp/CCBAC01/getItem?safeLetterNo={m.group(1)}"
        items.append(Item(
            external_id=f"mfds:{m.group(1)}", url=url, title=title,
            published=local_date(cells.get("공고일", ""), lang), doc_type=doc_type_for(title),
            lang=lang, body_text=summary or None,
            structured={"safe_letter_no": int(m.group(1)), "summary": summary or None,
                        "department": cells.get("담당부서") or None}))
    return items


def _page_url(url: str, page: int) -> str:
    return url if page <= 1 else f"{url}{'&' if '?' in url else '?'}page={page}"


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    for page in range(1, pages_to_read(ctx, source) + 1):
        f = ctx.get(_page_url(source.url, page))
        if f.status == 304:
            break
        got = parse_list(f, f.final_url, source)
        if page == 1:
            require(got or soup(f).select("a[href*='safeLetterNo=']"), f,
                    marker="safeLetterNo", empty_markers=("검색된 결과가 없습니다", "데이터가 없습니다"))
        if not got:
            break
        out.extend(got)
    return out


def parse_detail(html) -> tuple[str, list[str], list[str]]:
    """-> (body text, attachment download URLs, attachment file names)."""
    doc = soup(html)
    parts: list[str] = []
    for tr in doc.select("table.tb_base tr.pc-tr"):
        th = tr.select_one("th")
        td = tr.select_one("td")
        if th is None or td is None:
            continue
        label = node_text(th)
        if label in ("정보요약", "상세정보", "조치사항"):
            text = block_text(td)
            if text:
                parts.append(f"{label}\n{text}")
    urls: list[str] = []
    for node in doc.select("[onclick*='downEdmsFile']"):
        m = _EDMS.search(node.get("onclick") or "")
        if m and DOWNLOAD + m.group(1) not in urls:
            urls.append(DOWNLOAD + m.group(1))
    names = [node_text(s) for s in doc.select("span[id^=fileNameTd]")]
    return "\n\n".join(parts), urls, names


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    f = ctx.get(item.url)
    if f.status != 200:
        return item
    body, urls, names = parse_detail(f)
    if body:
        item.body_text = "\n\n".join(x for x in (item.body_text, body) if x)
    for u in urls:
        if u not in item.attachment_urls:
            item.attachment_urls.append(u)
    if names:
        item.structured = {**(item.structured or {}), "attachment_names": names}
    return item


__all__ = ["absolute", "fill_detail", "fetch_detail", "list_items", "parse_detail", "parse_list"]
