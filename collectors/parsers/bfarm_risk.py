"""PHAROS — BfArM (Germany) Risikoinformationen: Risikobewertungsverfahren and related lists.

Source: ``bfarm-risk``; ``source.url``:
``https://www.bfarm.de/DE/Arzneimittel/Pharmakovigilanz/Risikoinformationen/Risikobewertungsverfahren/_node.html``
Sister lists read the same way through ``extra_urls``:
``…/Risikoinformationen/Weitere-Arzneimittelrisiken/_node.html`` and
``…/Risikoinformationen/Aufforderung-zur-Textanpassung/_node.html``. (Rote-Hand-Briefe are the A1
feed ``bfarm-rhb``.)

Page structure relied on (checked 4 Nov 2026; all three lists again 5 Nov 2026): a sortable table,
``table tr`` with (``tbody`` is not required, header rows have no ``td``)

* td 1: the date "30.10.2026";
* td 2: ``a[href]`` — the title as published and the article
  ``/SharedDocs/Risikoinformationen/Pharmakovigilanz/DE/…/<slug>.html?nn=…``, then
  ``p.teasertext-wrapper`` holding ``span.wirkstoff-wrapper`` "Wirkstoff: Flupentixol/Melitracen"
  and a one-paragraph summary.

Detail page: body ``div.l-contentwrapper``; originals ``…pdf?__blob=publicationFile``.
External id: the article path without the ``nn`` navigation parameter.

doc_type by list: Risikobewertungsverfahren → ``safety_update``; Weitere-Arzneimittelrisiken →
``safety_alert``; Aufforderung-zur-Textanpassung → ``safety_update``. ``options.doc_type`` overrides.

Options: ``extra_urls``, ``doc_type``, ``include_keywords`` / ``exclude_keywords``, ``lang`` (``de``).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collectors.parsers._html_util import (absolute, fill_detail, keep, local_date, node_text,
                                           require)
from collectors.parsers.base import Item, SourceConfig, soup

_WIRKSTOFF = re.compile(r"^\s*Wirkstoffe?\s*:\s*", re.I)


def strip_nn(url: str) -> str:
    p = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if k != "nn"])
    return urlunsplit((p.scheme, p.netloc, p.path, query, ""))


def list_doc_type(url: str, source: SourceConfig) -> str:
    if (source.options or {}).get("doc_type"):
        return source.options["doc_type"]
    return "safety_alert" if "Weitere-Arzneimittelrisiken" in url else "safety_update"


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "de"
    doc_type = list_doc_type(base_url, source)
    items: list[Item] = []
    for tr in doc.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        a = tds[1].select_one("a[href]")
        if a is None:
            continue
        title = node_text(a)
        span = tds[1].select_one("span.wirkstoff-wrapper")
        substance = _WIRKSTOFF.sub("", node_text(span)) if span is not None else ""
        teaser = node_text(tds[1].select_one("p.teasertext-wrapper"))
        if not title or not keep(source, title, teaser):
            continue
        url = absolute(a["href"], base_url)
        items.append(Item(
            external_id=strip_nn(url), url=url, title=title,
            published=local_date(node_text(tds[0]), lang), doc_type=doc_type, lang=lang,
            body_text=teaser or None,
            structured={"wirkstoff": substance or None,
                        "list": urlsplit(base_url).path.rstrip("/").split("/")[-2]}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    urls = [source.url] + list((source.options or {}).get("extra_urls") or [])
    out: list[Item] = []
    for url in urls:
        f = ctx.get(url)
        if f.status == 304:
            continue
        require(soup(f).select("table tr td a[href]"), f, marker="<table",
                empty_markers=("Keine Einträge", "keine Treffer"))
        out.extend(parse_list(f, f.final_url, source))
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "div.l-contentwrapper",
                       patterns=(".pdf", "blob=publicationfile"))
