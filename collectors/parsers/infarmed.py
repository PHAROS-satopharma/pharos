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

The « Alertas » page lags: on 5 Nov 2026 it ended on 04/09/2026 and never listed circular 087 (Sterisets
recall, posted 03/11/2026) or 097 (Besilato de Atracúrio recall, posted 04/11/2026). Both were on the
medicines circulars page, so it is read too (``circulares_url``):

* ``div.result-item``: ``h3.title a[href]`` = the title and the circular itself
  (``/documents/15786/<folder>/<name>/<uuid>?version=…``), ``div.result-resume`` = "Circular Informativa
  n.º 097/CD7550.20.001 de 26/10/2026", ``div.result-path span`` = the day it was posted. Twenty a
  page, newest first; most are prices, export lists or prescribing rules, so only the alert series
  (``…550.20.001``, written ``/CD/`` or ``/CD7``) and titles starting « Recolha » / « Suspensão » /
  « Retirada » are kept. An alert on both pages is kept once (same circular number and year).

doc_type: titles starting « Recolha » → ``recall``; « Suspensão »/« Retirada » → ``recall``;
« Comunicação dirigida aos profissionais » / « DHPC » → ``dhpc``; otherwise ``safety_alert``.

Options:

* ``include_families`` — family labels to keep (default ``["Medicamento de uso humano"]``; ``[]``
  keeps every family).
* ``include_keywords`` / ``exclude_keywords``; ``max_pages`` (1) / ``backfill_pages`` (5).
* ``circulares_url`` — the circulars page also read (default ``CIRCULARES``; ``""`` reads only Alertas).
* ``lang`` (``pt``).
"""

from __future__ import annotations

import logging
import re

from collectors.parsers._html_util import (absolute, clean, fill_detail, keep, local_date,
                                           node_text, pages_to_read, require)
from collectors.parsers.base import Item, SourceConfig, soup

log = logging.getLogger(__name__)

_CIRC = re.compile(r"Circular\s+Informativa\s+N\.?\s*º\s*([\w/.-]+)", re.I)
_DATA = re.compile(r"Data\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", re.I)
_ID = re.compile(r"/journal_content/\d+/\d+/(\d+)")
_DOC = re.compile(r"/documents/\d+/\d+/[^/]+/([0-9a-f-]{36})")
_NUMBER = re.compile(r"N\.?\s*º\s*(\d+)\s*/", re.I)
_YEAR = re.compile(r"\d{1,2}/\d{1,2}/(\d{4})")
_ALERT_SERIES = re.compile(r"550\.20\.001")
CIRCULARES = "https://www.infarmed.pt/web/infarmed/entidades/medicamentos-uso-humano/circulares"


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


def circular_key(meta: str) -> tuple[int, str] | None:
    """(number, year) of "Circular Informativa N.º 088/CD/550.20.001 de 04/09/2026", or None."""
    num, year = _NUMBER.search(meta), _YEAR.search(meta)
    return (int(num.group(1)), year.group(1)) if num and year else None


def parse_circulares(html, base_url: str, source: SourceConfig) -> list[Item]:
    """The medicines circulars page: alert-series circulars and recalls only."""
    lang = source.lang or "pt"
    items: list[Item] = []
    for res in soup(html).select("div.result-item"):
        a = res.select_one("h3.title a[href]") or res.select_one("a[href]")
        if a is None:
            continue
        title = node_text(a)
        meta = node_text(res.select_one(".result-resume")).strip('"“” ')
        posted = local_date(node_text(res.select_one(".result-path")), lang)
        if not title or not (_ALERT_SERIES.search(meta) or doc_type_for(title) == "recall"):
            continue
        if not keep(source, title, meta):
            continue
        url = absolute(a["href"], base_url)
        m_doc = _DOC.search(url)
        circ = _CIRC.search(meta)
        items.append(Item(
            external_id=f"infarmed:doc:{m_doc.group(1)}" if m_doc else url, url=url, title=title,
            published=posted or local_date(meta, lang), doc_type=doc_type_for(title), lang=lang,
            body_text=meta or None, attachment_urls=[url],
            structured={"family": "Medicamento de uso humano",
                        "circular": circ.group(1) if circ else None}))
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
    circ_url = (source.options or {}).get("circulares_url", CIRCULARES)
    if circ_url:
        f = ctx.get(circ_url)
        if f.status not in (200, 304):
            log.warning("infarmed circulares %s: HTTP %s; only Alertas read", circ_url, f.status)
        elif f.status == 200:
            doc = soup(f)
            require(doc.select("div.result-item"), f, marker="result-item")
            known = {circular_key(it.body_text or "") for it in out} - {None}
            for it in parse_circulares(f, f.final_url, source):
                key = circular_key(it.body_text or "")
                if key is None or key not in known:
                    out.append(it)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    if item.external_id.startswith("infarmed:doc:"):
        return item          # the circular itself is the PDF, read as its attachment
    return fill_detail(item, ctx.get(item.url), "div.journal-content-article")
