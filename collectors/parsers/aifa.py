"""PHAROS — AIFA (Italy) safety communications.

Source: ``aifa-sicurezza``; ``source.url`` is the AIFA site search filtered to the
« Note Informative Importanti » (NIIS):
``https://www.aifa.gov.it/ricerca-aifa?searchKeywords=&structures=93604&adtCategories=1960204``
(25 per page). ``adtCategories=1960205`` is the AIFA/EMA communications list (``extra_urls``).

Page structure relied on (checked 4 Nov 2026):

* list: ``div.card`` → ``div[data-article-id]`` → ``h3 a.asset-link`` (href ``/-/<slug>``), a summary
  ``p``, and ``span.u-color-blu`` holding the date followed by the category. The date is dd/mm/yyyy
  in a browser, but a plain request (5 Nov 2026) gets Java's ``Thu Oct 08 00:00:00 CEST 2026``.
  The pager is JavaScript (``data-paginator``); only the first page is read unless
  ``options.page_param`` names the query parameter for further pages.
* detail: ``div.journal-content-article``; originals ``/documents/20142/…pdf``.

Options:

* ``extra_urls`` — further list URLs read the same way.
* ``doc_type`` — default ``dhpc`` (an NIIS is the Italian DHPC); titles starting « Comunicazione »
  become ``safety_update``.
* ``doc_type_by_url`` — ``{text in the list URL: doc_type}``: the AIFA/EMA communications list
  (``adtCategories=1960205``) holds communications, not DHPCs (5 Nov 2026: « EMA raccomanda… »,
  « AIFA richiama… »), so its items are ``safety_update``. A title starting « Nota Informativa
  Importante » is an NIIS and stays ``dhpc`` whichever list it is on.
* ``include_keywords`` / ``exclude_keywords``; ``page_param`` with ``max_pages`` (1) /
  ``backfill_pages`` (5).
* ``lang`` — default ``it``.
"""

from __future__ import annotations

import re
from datetime import date

from collectors.parsers._html_util import (absolute, fill_detail, keep, local_date, node_text,
                                           pages_to_read, require)
from collectors.parsers.base import Item, SourceConfig, soup

BASE = "https://www.aifa.gov.it"


_JAVA_DATE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                        r"\s+(\d{1,2})\s+\d{2}:\d{2}:\d{2}\s+[A-Z]{2,5}\s+(\d{4})")
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _date(meta: str, lang: str) -> date | None:
    m = _JAVA_DATE.search(meta or "")
    if m:
        try:
            return date(int(m.group(3)), _MONTHS.index(m.group(1)) + 1, int(m.group(2)))
        except ValueError:
            return None
    return local_date(meta, lang)


def _category(meta: str) -> str | None:
    rest = _JAVA_DATE.sub("", meta or "").strip()
    rest = re.sub(r"^\d{1,2}/\d{1,2}/\d{4}", "", rest).strip()
    return rest or None


def _page_url(url: str, page: int, param: str | None) -> str:
    return url if page <= 1 or not param else f"{url}{'&' if '?' in url else '?'}{param}={page}"


def parse_list(html, base_url: str, source: SourceConfig, doc_type: str | None = None) -> list[Item]:
    doc = soup(html)
    opts = source.options or {}
    lang = source.lang or "it"
    items: list[Item] = []
    for card in doc.select("div.card"):
        a = card.select_one("h3 a.asset-link[href]") or card.select_one("h3 a[href]")
        if a is None:
            continue
        title = node_text(a)
        summary = node_text(card.select_one("div.content > p") or card.select_one("p"))
        if not title or not keep(source, title, summary):
            continue
        url = absolute(a["href"], base_url or BASE)
        art = card.select_one("[data-article-id]")
        date_span = card.select_one("span.u-color-blu")
        meta = node_text(date_span)
        kind = doc_type or opts.get("doc_type", "dhpc")
        if title.casefold().startswith("comunicazione"):
            kind = "safety_update"
        if title.casefold().startswith("nota informativa importante"):
            kind = "dhpc"
        items.append(Item(
            external_id=(f"aifa:{art['data-article-id']}" if art is not None else url),
            url=url, title=title, published=_date(meta, lang), doc_type=kind, lang=lang,
            body_text=summary or None,
            structured={"category": _category(meta)}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    opts = source.options or {}
    urls = [source.url] + list(opts.get("extra_urls") or [])
    param = opts.get("page_param")
    pages = pages_to_read(ctx, source) if param else 1
    out: list[Item] = []
    seen: set[str] = set()
    by_url = opts.get("doc_type_by_url") or {}
    for base in urls:
        kind = next((t for key, t in by_url.items() if key in base), None)
        for page in range(1, pages + 1):
            f = ctx.get(_page_url(base, page, param))
            if f.status == 304:
                break
            if page == 1:
                require(soup(f).select("div.card h3 a"), f, marker="asset-link",
                        empty_markers=("Nessun risultato", "Non ci sono risultati"))
            batch = [it for it in parse_list(f, f.final_url, source, kind) if it.external_id not in seen]
            if not batch:
                break
            seen.update(it.external_id for it in batch)
            out.extend(batch)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "div.journal-content-article")
