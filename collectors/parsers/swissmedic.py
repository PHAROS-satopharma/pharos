"""PHAROS — Swissmedic (Switzerland), Health Professional Communications (DHPC / HPC).

Source: ``swissmedic-hpc``. Swissmedic publishes each letter in the language(s) it was sent in, so
the source reads every language page given and keeps titles as published:

* de ``https://www.swissmedic.ch/swissmedic/de/home/humanarzneimittel/marktueberwachung/health-professional-communication--hpc-.html``
* fr ``https://www.swissmedic.ch/swissmedic/fr/home/medicaments-a-usage-humain/surveillance-du-marche/health-professional-communication--hpc-.html``
* it ``https://www.swissmedic.ch/swissmedic/it/home/medicamenti-per-uso-umano/sorveglianza-del-mercato/health-professional-communication--hpc-.html``

Page structure relied on (checked 4 Nov 2026): ``div.mod-teaserlist`` → ``div.mod-teaser`` with
``p.teaserDate`` (dd.mm.yyyy), ``h3 a[href]`` (the title; detail page ``…/hpc-/<slug>.html``) and
``div.wrapper`` (one-line subject). 12 per page; further pages load by script, so only page 1 is
read (letters arrive far more slowly than 12 per 4-hourly run).

Detail page: body ``#content``; originals ``/dam/swissmedic/…pdf``.

doc_type: titles starting "DHPC" → ``dhpc``; "HPC" → ``safety_update``; otherwise ``safety_alert``.

Options:

* ``urls`` — mapping ``{lang: url}``; default: ``source.url`` with ``lang`` taken from the
  ``/swissmedic/<lang>/`` path segment.
* ``include_keywords`` / ``exclude_keywords``.
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, fill_detail, keep, local_date, node_text,
                                           require)
from collectors.parsers.base import Item, SourceConfig, soup

_LANG = re.compile(r"/swissmedic/(de|fr|it|en)/")


def doc_type_for(title: str) -> str:
    t = title.lstrip().upper()
    if t.startswith("DHPC"):
        return "dhpc"
    if t.startswith("HPC"):
        return "safety_update"
    return "safety_alert"


def parse_list(html, base_url: str, source: SourceConfig, lang: str) -> list[Item]:
    doc = soup(html)
    items: list[Item] = []
    for teaser in doc.select("div.mod-teaser"):
        a = teaser.select_one("h3 a[href]")
        if a is None:
            continue
        title = node_text(a)
        subject = node_text(teaser.select_one("div.wrapper"))
        if not title or not keep(source, title, subject):
            continue
        url = absolute(a["href"], base_url)
        items.append(Item(
            external_id=url, url=url, title=title,
            published=local_date(node_text(teaser.select_one("p.teaserDate")), lang),
            doc_type=doc_type_for(title), lang=lang, body_text=subject or None,
            structured={"subject": subject or None}))
    return items


def targets(source: SourceConfig) -> list[tuple[str, str]]:
    urls = (source.options or {}).get("urls")
    if isinstance(urls, dict) and urls:
        return [(lang, url) for lang, url in urls.items()]
    m = _LANG.search(source.url)
    return [(m.group(1) if m else (source.lang or "de"), source.url)]


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    for lang, url in targets(source):
        f = ctx.get(url)
        if f.status == 304:
            continue
        require(soup(f).select("div.mod-teaser h3 a"), f, marker="mod-teaserlist")
        out.extend(parse_list(f, f.final_url, source, lang))
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "#content", patterns=(".pdf",))
