"""PHAROS — WHO Medical Product Alerts (substandard and falsified medical products).

Source: ``who-alerts``; ``source.url``:
``https://www.who.int/teams/regulation-prequalification/incidents-and-SF/full-list-of-who-medical-product-alerts``

Page structure relied on (checked 4 Nov 2026): ``div.list-view--item a.link-container[href]``
(``/news/item/03-07-2026-medical-product-alert-n-3-2026--falsified-darzalex-(daratumumab)``) holding
``span.timestamp`` ("3 July 2026"), ``div.sf-tags-list-item`` ("Medical product alert") and
``p.heading`` (the title, "Medical Product Alert N°3/2026: Falsified DARZALEX (daratumumab)").
The whole history (~90 alerts) is on one page; the alert number is used as external id when present.

Detail page body: ``article`` / ``div.sf-detail-body-wrapper``; doc_type ``safety_alert``.

Options: ``include_keywords`` / ``exclude_keywords``; ``max_items`` (default 30 on a normal run,
every item on a backfill); ``lang`` (``en``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, clean, fill_detail, keep, local_date,
                                           node_text, require)
from collectors.parsers.base import Item, SourceConfig, soup

_NUMBER = re.compile(r"N\s*[°º]\s*(\d+)\s*/\s*(\d{4})", re.I)


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "en"
    items: list[Item] = []
    seen: set[str] = set()
    for card in doc.select("div.list-view--item"):
        a = card.select_one("a.link-container[href]") or card.select_one("a[href]")
        if a is None:
            continue
        title = node_text(card.select_one("p.heading")) or clean(a.get("aria-label"))
        if not title or not keep(source, title):
            continue
        url = absolute(a["href"], base_url)
        m = _NUMBER.search(title)
        ext = f"who-mpa:{m.group(2)}-{int(m.group(1)):02d}" if m else url
        if ext in seen:
            continue
        seen.add(ext)
        tags = [node_text(t) for t in card.select("div.sf-tags-list-item")]
        items.append(Item(
            external_id=ext, url=url, title=title,
            published=local_date(node_text(card.select_one("span.timestamp")), lang),
            doc_type="safety_alert", lang=lang, structured={"tags": tags or None}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    items = parse_list(f, f.final_url, source)
    require(items or soup(f).select("div.list-view--item a[href]"), f, marker="list-view")
    if not ctx.backfill:
        items = items[: int((source.options or {}).get("max_items", 30))]
    return items


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    f = ctx.get(item.url)
    body = "div.sf-detail-body-wrapper" if b"sf-detail-body-wrapper" in (f.content or b"") \
        else "article"
    return fill_detail(item, f, body)
