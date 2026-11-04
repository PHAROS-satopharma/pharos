"""PHAROS — TGA (Australia) safety alerts and safety updates, read with the headless browser.

Sources (``options.page`` or the source id says which):

* ``tga-alerts`` — ``https://www.tga.gov.au/safety/safety-alerts``; articles ``/news/safety-alerts/<slug>``;
  doc_type ``safety_alert`` (titles with "recall" → ``recall``).
* ``tga-updates`` — ``https://www.tga.gov.au/news/safety-updates``; articles
  ``/news/safety-updates/<slug>``; doc_type ``safety_update``.

On 4 Nov 2026 a plain request from here timed out after 40 s with no bytes (the site drops
non-browser clients), so both sources are ``channel: browser``; the e-mail newsletter
(``tga-email``, parser ``email_inbox``) is the second path in. A challenge page raises
``SourceBlocked`` (``FetchContext.browser_get``); the parser never tries to get past one.

Page structure relied on: Drupal listing cards; each card links to the article and shows the date
("4 November 2026"). Link mode of ``generic_html`` is used so a card redesign does not break it.
Detail body: ``main`` (``detail_selector``).

Options: ``page`` (``alerts`` | ``updates``), ``link_pattern``, ``wait_selector``,
``detail_selector``, ``include_keywords`` / ``exclude_keywords``; ``lang`` (``en``).
"""

from __future__ import annotations

from collectors.parsers import generic_html
from collectors.parsers.base import Item, SourceConfig

PAGES = {
    "alerts": {"link_pattern": r"/news/safety-alerts/[^/?#]+/?$", "doc_type": "safety_alert",
               "doc_type_rules": [{"match": r"\brecall", "doc_type": "recall"}]},
    "updates": {"link_pattern": r"/news/safety-updates/[^/?#]+/?$", "doc_type": "safety_update"},
}


def page_kind(source: SourceConfig) -> str:
    kind = (source.options or {}).get("page")
    if kind:
        return str(kind).lower()
    return "updates" if "update" in source.id or "update" in source.url else "alerts"


def options_for(source: SourceConfig) -> dict:
    opts = dict(source.options or {})
    for k, v in PAGES[page_kind(source)].items():
        opts.setdefault(k, v)
    opts.setdefault("browser", True)
    opts.setdefault("wait_selector", "main a[href*='/news/']")
    opts.setdefault("detail_selector", "main")
    opts.setdefault("lang", source.lang or "en")
    return opts


def list_items(ctx, source: SourceConfig) -> list[Item]:
    return generic_html.list_with(ctx, source, options_for(source))


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    opts = options_for(source)
    sel = opts["detail_selector"]
    f = ctx.browser_get(item.url, wait_selector=sel) if opts.get("browser") else ctx.get(item.url)
    return generic_html.fill_detail(item, f, sel)
