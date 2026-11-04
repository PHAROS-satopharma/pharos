"""PHAROS — Lyfjastofnun / IMA (Iceland), « Bréf til heilbrigðisstarfsmanna (DHPC) ».

Source: ``ima-dhpc``; ``source.url``:
``https://www.lyfjastofnun.is/lyf/lyfjagat/bref-til-heilbrigdisstarfsmanna-dhpc/``

Page structure relied on (checked 4 Nov 2026): one WordPress table ``figure.wp-block-table table``
whose first row is a plain ``td`` header in bold: Nafn lyfs | Innihaldsefni | Dagsetning | Skjöl.

* Nafn lyfs — product name(s), the item title exactly as published (e.g. "Ocrevus");
* Innihaldsefni — active substance(s);
* Dagsetning — Icelandic month and year ("Október 2026", "Ágúst 2026") → 1st of the month;
* Skjöl — ``a`` "Bréf" → ``/wp-content/uploads/…pdf`` (the letter), plus any further attachments.

The item URL is the letter PDF; every PDF in the row is an attachment.

Options: ``include_keywords`` / ``exclude_keywords``; ``doc_type`` (``dhpc``); ``lang`` (``is``).
"""

from __future__ import annotations

from collectors.parsers._html_util import (column, keep, links_in, local_date, node_text, require,
                                           table_records)
from collectors.parsers.base import Item, SourceConfig, soup

HINTS = ("nafn lyfs", "innihaldsefni", "dagsetning")


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "is"
    items: list[Item] = []
    seen: set[str] = set()
    tables = doc.select("figure.wp-block-table table") or doc.select("table")
    for table in tables:
        for tds, header in table_records(table, HINTS):
            iname = column(header, "nafn", default=0)
            isub = column(header, "innihald", default=1)
            idate = column(header, "dagsetning", default=2)
            if max(iname, isub, idate) >= len(tds):
                continue
            pdfs = links_in(tds, base_url, patterns=(".pdf",))
            if not pdfs:
                continue
            name, substance = node_text(tds[iname]), node_text(tds[isub])
            if pdfs[0] in seen or not name or not keep(source, name, substance):
                continue
            seen.add(pdfs[0])
            when = node_text(tds[idate])
            items.append(Item(
                external_id=pdfs[0], url=pdfs[0], title=name, published=local_date(when, lang),
                doc_type=(source.options or {}).get("doc_type", "dhpc"), lang=lang,
                body_text="\n".join(x for x in (name, substance) if x), attachment_urls=pdfs,
                structured={"substance": substance, "date_text": when}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    items = parse_list(f, f.final_url, source)
    require(items or soup(f).select("figure.wp-block-table a[href$='.pdf']"), f,
            marker="wp-block-table")
    return items
