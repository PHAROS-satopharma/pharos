"""PHAROS — CBG-MEB (Netherlands) news, read with the headless browser.

Source: ``cbg-news``; ``source.url``: ``https://www.cbg-meb.nl/actueel/nieuws``.

The site is a Next.js app: the HTML a plain request gets (``tests/fixtures/cbg-news/list.html``,
4 Nov 2026) carries the page frame but no news items, which are drawn client-side. No public JSON
or RSS endpoint was found (``/actueel/nieuws/rss`` answers 404). So the source is
``channel: browser`` and the parser reads the rendered page.

Page structure relied on (rendered): links to articles under ``/actueel/nieuws/…`` — normally
``/actueel/nieuws/YYYY/MM/DD/<slug>``, whose path also gives the date when the card shows none.
The title is the link text as published (Dutch). doc_type from Dutch words in the title:
« DHPC » / « brief aan zorgverleners » → ``dhpc``; « terughaal » / « teruggeroepen » → ``recall``;
« veiligheid » / « risico » / « bijwerking » / « PRAC » → ``safety_alert``; otherwise ``other``.

Options: ``link_pattern``, ``wait_selector`` (``a[href*='/actueel/nieuws/']``), ``detail_selector``
(``main``), ``include_keywords`` / ``exclude_keywords``; ``lang`` (``nl``).
"""

from __future__ import annotations

import re
from datetime import date

from collectors.parsers import generic_html
from collectors.parsers.base import Item, SourceConfig

LINK_PATTERN = r"/actueel/nieuws/(?:\d{4}/\d{2}/\d{2}/)?[a-z0-9][^/?#]*/?$"
_PATH_DATE = re.compile(r"/actueel/nieuws/(\d{4})/(\d{2})/(\d{2})/")

DOC_TYPE_RULES = [
    {"match": r"\bDHPC\b|brief aan (?:zorgverleners|artsen|apothekers)", "doc_type": "dhpc"},
    {"match": r"terughaal|teruggeroepen|terugroep", "doc_type": "recall"},
    {"match": r"veiligheid|risico|bijwerking|\bPRAC\b|waarschuw", "doc_type": "safety_alert"},
]


def options_for(source: SourceConfig) -> dict:
    opts = dict(source.options or {})
    opts.setdefault("browser", True)
    opts.setdefault("link_pattern", LINK_PATTERN)
    opts.setdefault("wait_selector", "a[href*='/actueel/nieuws/']")
    opts.setdefault("detail_selector", "main")
    opts.setdefault("doc_type_rules", DOC_TYPE_RULES)
    opts.setdefault("doc_type", "other")
    opts.setdefault("lang", source.lang or "nl")
    return opts


def date_from_path(url: str) -> date | None:
    m = _PATH_DATE.search(url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_rendered(html, base_url: str, source: SourceConfig) -> list[Item]:
    opts = options_for(source)
    items = [it for it in generic_html.extract(html, base_url, source, opts)
             if not it.url.rstrip("/").endswith("/actueel/nieuws")]
    for it in items:
        if it.published is None:
            it.published = date_from_path(it.url)
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    opts = options_for(source)
    f = generic_html.read_page(ctx, source.url, opts)
    items = parse_rendered(f, f.final_url, source)
    generic_html.require(items or generic_html.raw_nodes(f, opts), f, marker="/actueel/nieuws/")
    return items


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    sel = options_for(source)["detail_selector"]
    return generic_html.fill_detail(item, ctx.browser_get(item.url, wait_selector=sel), sel)
