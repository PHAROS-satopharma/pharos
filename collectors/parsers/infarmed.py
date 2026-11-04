"""PHAROS — INFARMED (Portugal) « Alertas » (Circulares Informativas).

Source: ``infarmed-circulares``; ``source.url``: ``https://www.infarmed.pt/web/infarmed/alertas``
(10 per page).

Page structure relied on (checked 4 Nov 2026):

* list: ``div#tituloADTAlertas article.event > a.event-link[href]``
  (``/web/infarmed/alertas/-/journal_content/56/15786/<article id>``), inside it
  ``span.font-icon[title]`` = the product family ("Medicamento de uso humano", "Dispositivos
  médicos", "Produtos cosméticos"…), ``h4.title`` = the title, then ``p`` lines
  "Circular Informativa N.º 088/CD/550.20.001 de 04/09/2026" and/or "Data: 28/08/2026".
* paging: Liferay links ``…_cur=2`` in the pager; the parser follows the link for the next page.
* detail: ``div.journal-content-article``; originals on ``extranet.infarmed.pt/…pdf``.

doc_type: titles starting « Recolha » → ``recall``; « Suspensão »/« Retirada » → ``recall``;
« Comunicação dirigida aos profissionais » / « DHPC » → ``dhpc``; otherwise ``safety_alert``.

Options:

* ``include_families`` — family labels to keep (default ``["Medicamento de uso humano"]``; ``[]``
  keeps every family).
* ``include_keywords`` / ``exclude_keywords``; ``max_pages`` (1) / ``backfill_pages`` (5).
* ``lang`` (``pt``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, clean, fill_detail, keep, local_date,
                                           node_text, pages_to_read, require)
from collectors.parsers.base import Item, SourceConfig, soup

_CIRC = re.compile(r"Circular\s+Informativa\s+N\.?\s*º\s*([\w/.-]+)", re.I)
_DATA = re.compile(r"Data\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_ID = re.compile(r"/journal_content/\d+/\d+/(\d+)")


def doc_type_for(title: str) -> str:
    t = title.casefold()
    if t.startswith(("recolha", "suspensão", "suspensao", "retirada")):
        return "recall"
    if "profissionais de saúde" in t or "dhpc" in t or t.startswith("comunicação dirigida"):
        return "dhpc"
    return "safety_alert"


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    opts = source.options or {}
    families = opts.get("include_families", ["Medicamento de uso humano"])
    wanted = {f.casefold() for f in families or []}
    lang = source.lang or "pt"
    scope = doc.select_one("#tituloADTAlertas") or doc
    items: list[Item] = []
    for art in scope.select("article.event"):
        a = art.select_one("a.event-link[href]") or art.select_one("a[href]")
        if a is None:
            continue
        icon = art.select_one("span.font-icon[title]")
        family = clean(icon["title"]) if icon is not None else ""
        if wanted and family.casefold() not in wanted:
            continue
        title = node_text(art.select_one("h4.title") or art.select_one("h4"))
        lines = [node_text(p) for p in art.select("p")]
        meta = " ".join(lines)
        if not title or not keep(source, title, meta):
            continue
        url = absolute(a["href"], base_url)
        m_id = _ID.search(url)
        circ = _CIRC.search(meta)
        m_date = _DATA.search(meta)
        published = local_date(m_date.group(1), lang) if m_date else local_date(meta, lang)
        items.append(Item(
            external_id=f"infarmed:{m_id.group(1)}" if m_id else url, url=url, title=title,
            published=published, doc_type=doc_type_for(title), lang=lang,
            body_text=meta or None,
            structured={"family": family or None, "circular": circ.group(1) if circ else None}))
    return items


def _next_page(doc, base_url: str, page: int) -> str | None:
    for a in doc.select("a[href*='_cur=']"):
        if re.search(rf"_cur={page}(?:\D|$)", a["href"]):
            return absolute(a["href"], base_url)
    return None


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    url: str | None = source.url
    for page in range(1, pages_to_read(ctx, source) + 1):
        if url is None:
            break
        f = ctx.get(url)
        if f.status == 304:
            break
        doc = soup(f)
        if page == 1:
            require(doc.select("article.event"), f, marker="tituloADTAlertas")
        out.extend(parse_list(f, f.final_url, source))
        url = _next_page(doc, f.final_url, page + 1)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "div.journal-content-article")
