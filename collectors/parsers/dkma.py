"""PHAROS — Lægemiddelstyrelsen / DKMA (Denmark), DHPC letters sent ("Udsendte meddelelser").

Source: ``dkma-dhpc``; ``source.url``:
``https://laegemiddelstyrelsen.dk/da/bivirkninger/direkte-sikkerhedsinformation/udsendte-meddelelser/``
(the older ``…/breve-til-sundhedspersonale-dhpc/`` address answers 404).

Page structure relied on (checked 4 Nov 2026): one or more tables in ``div.bodytext`` (or the main
column), header row "DHPC | Brev sendt", then one row per letter:

* td 1: ``a[href="~/media/<32 hex>.ashx"]`` — the letter itself (a PDF served by Sitecore); the
  link text is the title as published, e.g. "Ocrevus (ocrelizumab)".
* td 2: the Danish date the letter was sent, "02.november 2026" or "8. oktober 2026".

The item URL is the PDF, which is also its only attachment.

Options: ``include_keywords`` / ``exclude_keywords``; ``doc_type`` (``dhpc``); ``lang`` (``da``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import absolute, keep, local_date, node_text, require
from collectors.parsers.base import Item, SourceConfig, soup

HOST = "https://laegemiddelstyrelsen.dk"
_MEDIA = re.compile(r"/media/([0-9A-Fa-f]{32})\.ashx", re.I)


def media_url(href: str, base_url: str) -> str:
    href = href.strip()
    if href.startswith("~/"):
        return HOST + href[1:]
    return absolute(href, base_url)


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    scope = doc.select_one("div.bodytext") or doc.select_one("main") or doc
    lang = source.lang or "da"
    doc_type = (source.options or {}).get("doc_type", "dhpc")
    items: list[Item] = []
    seen: set[str] = set()
    for tr in scope.select("table tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        a = tds[0].select_one("a[href]")
        if a is None:
            continue
        title = node_text(a) or node_text(tds[0])
        url = media_url(a["href"], base_url)
        m = _MEDIA.search(url)
        ext = f"dkma:{m.group(1).upper()}" if m else url
        if ext in seen or not title or not keep(source, title):
            continue
        seen.add(ext)
        sent = node_text(tds[1])
        items.append(Item(external_id=ext, url=url, title=title,
                          published=local_date(sent, lang), doc_type=doc_type, lang=lang,
                          attachment_urls=[url], structured={"sent": sent}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    items = parse_list(f, f.final_url, source)
    require(items or soup(f).select("table a[href*='/media/']"), f, marker="Brev sendt")
    return items
