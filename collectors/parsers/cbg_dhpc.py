"""PHAROS — CBG-MEB (Netherlands), the DHPC letters (« Overzicht DHPC's »).

Source: ``cbg-dhpc``; ``source.url``: ``https://www.cbg-meb.nl/sitemap/1.xml``

CBG's own DHPC overview is drawn by script, and its news list (``cbg-news``) misses letters: on
5 Nov 2026 "DHPC Caelyx" (30 Oct) and "DHPC Tavneos" (16 Jul) had no news item at all. Every
letter is a document page ``/documenten/<YYYY>/<MM>[/<DD>]/dhpc-<name>``, and the site's plain
XML sitemap lists the most recently changed pages first, 100 per file. The first ``sitemaps``
files (default 3, about four months of changes) are read and the letter pages kept.

* the date comes from the page address (a month-only address, ``/documenten/2026/07/dhpc-ixchiq``,
  is dated the 1st);
* the detail page gives the title as published (``h1``, "DHPC Caelyx"), the summary in ``main``
  and the letter PDF (``/site/binaries/site-content/collections/documents/…/261030-dhpc-caelyx.pdf``).

Options: ``sitemaps`` (3); ``doc_type`` (``dhpc``); ``lang`` (``nl``); ``include_keywords`` /
``exclude_keywords``.
"""

from __future__ import annotations

import re
from datetime import date

from collectors.parsers._html_util import fill_detail, keep, node_text
from collectors.parsers.base import Item, ParseError, SourceConfig, soup

LETTER = re.compile(r"https://www\.cbg-meb\.nl/documenten/(\d{4})/(\d{2})(?:/(\d{2}))?/(dhpc-[a-z0-9-]+)/?$")
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


def _date(y: str, m: str, d: str | None) -> date | None:
    try:
        return date(int(y), int(m), int(d or 1))
    except ValueError:
        return None


def parse_sitemap(content: bytes | str, source: SourceConfig) -> list[Item]:
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
    if "<urlset" not in text:
        raise ParseError("CBG sitemap is not a urlset")
    lang = source.lang or "nl"
    items: list[Item] = []
    for url in LOC.findall(text):
        m = LETTER.match(url)
        if not m:
            continue
        y, mo, d, slug = m.groups()
        # A placeholder until the page is read: the slug, "dhpc-caelyx" → "DHPC caelyx".
        title = "DHPC " + slug[5:].replace("-", " ")
        if not keep(source, title):
            continue
        items.append(Item(external_id=url.rstrip("/"), url=url, title=title, published=_date(y, mo, d),
                          doc_type=(source.options or {}).get("doc_type", "dhpc"), lang=lang,
                          structured={"slug": slug}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    n = int((source.options or {}).get("sitemaps", 3))
    base = source.url.rsplit("/", 1)[0]
    out: list[Item] = []
    seen: set[str] = set()
    for k in range(1, n + 1):
        # The first file must answer; a later one that is missing only ends the reading.
        f = ctx.get(f"{base}/{k}.xml", accept="application/xml", raise_for_status=k == 1)
        if f.status == 304:
            continue
        if f.status != 200:
            break
        for it in parse_sitemap(f.content, source):
            if it.external_id not in seen:
                seen.add(it.external_id)
                out.append(it)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    f = ctx.get(item.url)
    if f.status == 200 and f.content:
        h1 = node_text(soup(f).select_one("h1"))
        if h1:
            item.title = h1
    return fill_detail(item, f, "main")
