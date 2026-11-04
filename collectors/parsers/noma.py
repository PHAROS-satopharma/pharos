"""PHAROS — DMP / NoMA (Norway), « Kjære helsepersonell »-brev (DHPC letters).

Source: ``noma-dhpc``; ``source.url``:
``https://www.dmp.no/bivirkninger-og-sikkerhet/tiltak-for-a-forebygge-bivirkninger/sikkerhetsinformasjon-til-helsepersonell-og-pasient/kjere-helsepersonell-brev``

Page structure relied on (checked 4 Nov 2026): one ``details.accordion-block`` per year (summary
"2026"), each holding a table with ``th`` headers Preparatnavn | Virkestoff | Tittel/tema | Dato:

* Preparatnavn: ``a[href="/globalassets/…pdf"]`` — the letter (PDF), text = product name(s);
* Virkestoff: active substance as published (Norwegian INN spelling, e.g. "okrelizumab");
* Tittel/tema: the letter's subject — used as the item title, exactly as published;
* Dato: month and year only ("Oktober 2026") → the 1st of that month.

The item URL is the PDF (also its only attachment). ``body_text`` joins product, substance and
subject so the matcher sees all three.

Options: ``include_keywords`` / ``exclude_keywords``; ``years`` — how many year blocks to read
(default 2; a backfill reads all); ``doc_type`` (``dhpc``); ``lang`` (``nb``).
"""

from __future__ import annotations

from collectors.parsers._html_util import (absolute, column, keep, local_date, node_text, require,
                                           table_records)
from collectors.parsers.base import Item, SourceConfig, soup

HINTS = ("preparatnavn", "virkestoff", "dato")


def parse_list(html, base_url: str, source: SourceConfig, *, years: int | None = None) -> list[Item]:
    doc = soup(html)
    opts = source.options or {}
    lang = source.lang or "nb"
    blocks = doc.select("details.accordion-block") or [doc]
    if years:
        blocks = blocks[:years]
    items: list[Item] = []
    seen: set[str] = set()
    for block in blocks:
        for table in block.select("table"):
            for tds, header in table_records(table, HINTS):
                ip = column(header, "preparat", default=0)
                iv = column(header, "virkestoff", default=1)
                it = column(header, "tittel", "tema", default=2)
                idt = column(header, "dato", default=3)
                if max(ip, iv, it, idt) >= len(tds):
                    continue
                a = tds[ip].select_one("a[href]") or next(
                    (c.select_one("a[href]") for c in tds if c.select_one("a[href]")), None)
                if a is None:
                    continue
                url = absolute(a["href"], base_url)
                product, substance = node_text(tds[ip]), node_text(tds[iv])
                title = node_text(tds[it]) or product
                if url in seen or not title or not keep(source, title, product, substance):
                    continue
                seen.add(url)
                dato = node_text(tds[idt])
                items.append(Item(
                    external_id=url, url=url, title=title, published=local_date(dato, lang),
                    doc_type=opts.get("doc_type", "dhpc"), lang=lang,
                    body_text="\n".join(x for x in (product, substance, title) if x),
                    attachment_urls=[url],
                    structured={"product": product, "substance": substance, "date_text": dato}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    years = None if ctx.backfill else int((source.options or {}).get("years", 2))
    items = parse_list(f, f.final_url, source, years=years)
    require(items or soup(f).select("details.accordion-block table a[href]"), f,
            marker="accordion-block")
    return items
