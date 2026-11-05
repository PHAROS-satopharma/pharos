"""PHAROS — configurable HTML list parser (Arab regulators, user-added sources, browser pages).

Used by ``eda-eg``, ``sfda-sa``, ``jfda-jo``, ``uae-mohap`` and any user-added HTML source, and
underneath the browser parsers ``famhp``, ``cbg`` and ``tga``. Everything is driven by
``source.options``; titles are kept exactly as published (Arabic, English or both).

Two modes:

* **item mode** (``item_selector`` set): every node matching ``item_selector`` (a card, a list item
  or a table row) is one notice. Inside it ``link_selector`` (default ``a[href]``) gives the URL,
  ``title_selector`` the title (default: the link text, else the item text), ``date_selector`` the
  date (default: the first date anywhere in the item), ``summary_selector`` a summary and
  ``tag_selector`` a category label.
* **link mode** (no ``item_selector``): every ``a[href]`` whose href matches ``link_pattern`` is one
  notice; its date is the first date found in its nearest ancestor that holds no other such link.

Options (all optional unless said):

* ``item_selector``, ``link_selector``, ``title_selector``, ``date_selector``,
  ``summary_selector``, ``tag_selector`` — CSS selectors as above;
* ``link_pattern`` — regex an href must match (required in link mode);
* ``include_tags`` — keep only items whose tag text is one of these (e.g. ``["دواء"]``);
* ``id_attr`` — attribute of the item node used as external id (e.g. ``data-history-node-id``);
  default: the absolute URL;
* ``doc_type`` (``safety_alert``) and ``doc_type_rules`` — ``[{match: <regex on title>, doc_type:
  <value>}]``, first match wins;
* ``browser`` — read the page with the shared headless browser (``ctx.browser_get``);
  ``wait_selector`` is then awaited (default: ``item_selector``);
* ``extra_urls`` — more list pages read the same way; or ``pages`` — a list of option dicts, one
  per list page (each with its own ``url`` and any option above), for a source whose pages differ;
  ``{year}`` in a URL is the current year (and last year too in January and on a backfill — a
  year's page may not exist yet in January: its 404 is skipped while last year's page answers);
* built-in ``PRESETS`` (bottom of this module) supply the options for ``eda-eg``, ``sfda-sa`` and
  ``jfda-jo``; ``source.options`` override them key by key;
* ``detail_selector`` — CSS of the notice body on the detail page; without it ``fetch_detail``
  only collects PDF links from the item itself;
* ``lang`` — BCP-47 of the items (default: the source's first language); ``item_lang_detect``
  (true) marks an item ``en`` when its title has no Arabic letters on an ``ar`` source;
* ``include_keywords`` / ``exclude_keywords``; ``allow_empty`` — the page may legitimately list
  nothing (otherwise an empty page raises ``ParseError``).

Example (EDA Egypt, DHPC table: content | date | PDF)::

    item_selector: "table tbody tr"
    title_selector: "td:nth-of-type(1)"
    date_selector: "td:nth-of-type(2)"
    link_selector: "a[href]"
    doc_type: dhpc
"""

from __future__ import annotations

import re
from datetime import date

from collectors.parsers._html_util import (absolute, block_text, clean, fill_detail, keep,
                                           links_in, local_date, node_text, require)
from collectors.parsers.base import FetchError, Item, NotSetUp, ParseError, SourceConfig, soup

_ARABIC = re.compile(r"[؀-ۿ]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _date_from(text: str, lang: str | None):
    return local_date(clean(text).translate(_ARABIC_DIGITS), lang)


def doc_type_for(title: str, opts: dict) -> str:
    for rule in opts.get("doc_type_rules") or []:
        try:
            if re.search(rule.get("match", ""), title, re.I):
                return rule.get("doc_type", "other")
        except re.error:
            continue
    return opts.get("doc_type", "safety_alert")


def _item_lang(title: str, lang: str | None, opts: dict) -> str | None:
    if lang and lang.startswith("ar") and opts.get("item_lang_detect", True) and title \
            and not _ARABIC.search(title):
        return "en"
    return lang


def _make(url: str, title: str, when, opts: dict, lang: str | None, *, ext: str | None = None,
          summary: str = "", tag: str = "", attachments: list[str] | None = None) -> Item:
    attachments = list(attachments or [])
    if url.lower().split("?")[0].endswith(".pdf") and url not in attachments:
        attachments.insert(0, url)
    structured = {k: v for k, v in (("tag", tag), ("summary", summary)) if v}
    return Item(external_id=ext or url, url=url, title=title, published=when,
                doc_type=doc_type_for(title, opts), lang=_item_lang(title, lang, opts),
                body_text=summary or None, attachment_urls=attachments,
                structured=structured or None)


def extract(html, base_url: str, source: SourceConfig, opts: dict | None = None) -> list[Item]:
    """Items of one list page, per ``opts`` (default: ``source.options``)."""
    opts = dict(source.options or {}) if opts is None else opts
    doc = soup(html)
    lang = opts.get("lang") or source.lang
    items: list[Item] = []
    seen: set[str] = set()
    pattern = re.compile(opts["link_pattern"]) if opts.get("link_pattern") else None
    include_tags = {clean(t) for t in opts.get("include_tags") or []}

    if opts.get("item_selector"):
        for node in doc.select(opts["item_selector"]):
            links = node.select(opts.get("link_selector") or "a[href]")
            links = [a for a in links if a.get("href") and not a["href"].startswith(
                ("#", "javascript:", "mailto:"))]
            if pattern is not None:
                links = [a for a in links if pattern.search(a["href"])]
            if not links:
                continue
            url = absolute(links[0]["href"], base_url)
            tsel = opts.get("title_selector")
            title = node_text(node.select_one(tsel)) if tsel else node_text(links[0])
            if not title:
                title = clean(links[0].get("title")) or node_text(node)
            dsel = opts.get("date_selector")
            when = _date_from(node_text(node.select_one(dsel)) if dsel else node_text(node), lang)
            ssel = opts.get("summary_selector")
            summary = block_text(node.select_one(ssel)) if ssel else ""
            gsel = opts.get("tag_selector")
            tag = node_text(node.select_one(gsel)) if gsel else ""
            if include_tags and tag not in include_tags:
                continue
            ext = None
            if opts.get("id_attr") and node.get(opts["id_attr"]):
                ext = f"{source.id}:{node[opts['id_attr']]}"
            key = ext or url
            if key in seen or not title or not keep(source, title, summary):
                continue
            seen.add(key)
            items.append(_make(url, title, when, opts, lang, ext=ext, summary=summary, tag=tag,
                               attachments=links_in([node], base_url)))
        return items

    if pattern is None:
        raise ParseError(f"{source.id}: generic_html needs item_selector or link_pattern")
    anchors = [a for a in doc.select("a[href]") if pattern.search(a["href"])]
    for a in anchors:
        url = absolute(a["href"], base_url)
        title = node_text(a) or clean(a.get("title"))
        if url in seen or not title:
            continue
        when = None
        node = a
        for _ in range(4):
            node = node.parent
            if node is None:
                break
            inner = [x for x in node.select("a[href]") if pattern.search(x["href"])
                     and absolute(x["href"], base_url) != url]
            if inner:
                break
            when = _date_from(node_text(node), lang)
            if when:
                break
        if not keep(source, title):
            continue
        seen.add(url)
        items.append(_make(url, title, when, opts, lang))
    return items


def raw_nodes(html, opts: dict) -> list:
    """The item nodes (or matching links) on the page before any keyword/tag filter."""
    doc = soup(html)
    if opts.get("item_selector"):
        return [n for n in doc.select(opts["item_selector"]) if n.select_one("a[href]")]
    if opts.get("link_pattern"):
        rx = re.compile(opts["link_pattern"])
        return [a for a in doc.select("a[href]") if rx.search(a["href"])]
    return []


def read_page(ctx, url: str, opts: dict, *, missing_ok: bool = False):
    if opts.get("browser"):
        return ctx.browser_get(url, wait_selector=opts.get("wait_selector")
                               or opts.get("item_selector"))
    return ctx.get(url, raise_for_status=not missing_ok)


def _expand(url: str, backfill: bool, today: date | None = None) -> list[str]:
    """``{year}`` in a URL → this year (and last year in January and on a backfill)."""
    if "{year}" not in url:
        return [url]
    today = today or date.today()
    year = today.year
    years = [year, year - 1] if backfill or today.month == 1 else [year]
    return [url.replace("{year}", str(y)) for y in years]


def pages_for(source: SourceConfig, opts: dict) -> list[dict]:
    """One options dict per list page: ``opts["pages"]`` entries (each merged over the source
    options), else ``url``/``source.url`` plus ``extra_urls``."""
    base = {k: v for k, v in opts.items() if k not in ("pages", "extra_urls")}
    if opts.get("pages"):
        return [{**base, **page} for page in opts["pages"]]
    urls = [opts.get("url") or source.url] + list(opts.get("extra_urls") or [])
    return [{**base, "url": u} for u in urls]


def list_with(ctx, source: SourceConfig, opts: dict) -> list[Item]:
    pages = pages_for(source, opts)
    if any(not (p.get("item_selector") or p.get("link_pattern")) for p in pages):
        # e.g. uae-mohap: no preset until its page has been seen; say so before fetching anything
        raise NotSetUp(f"{source.id} has no reading rules yet. Its page has not been checked, so "
                       "item_selector or link_pattern must be added to the source options first.")
    out: list[Item] = []
    seen: set[str] = set()
    for page in pages:
        urls = _expand(page.get("url") or source.url, bool(getattr(ctx, "backfill", False)))
        missing = 0
        checked = False
        for url in urls:
            # A year's page that is not there yet (January) is skipped while another year answers.
            f = read_page(ctx, url, page, missing_ok=len(urls) > 1)
            if f.status == 404:
                missing += 1
                continue
            if f.status >= 400:
                raise FetchError(f.status, url)
            if f.status == 304:
                checked = True
                continue
            got = extract(f, f.final_url, source, page)
            if not page.get("allow_empty") and not checked:
                require(got or raw_nodes(f, page), f, marker=page.get("item_selector"),
                        empty_markers=page.get("empty_markers") or ())
            checked = True
            for it in got:
                if it.external_id not in seen:
                    seen.add(it.external_id)
                    out.append(it)
        if missing == len(urls):
            raise FetchError(404, urls[0])
    return out


def options_for(source: SourceConfig) -> dict:
    """``source.options`` over the built-in preset for this source id (``PRESETS``)."""
    opts = dict(PRESETS.get(source.id, {}))
    opts.update(source.options or {})
    return opts


def list_items(ctx, source: SourceConfig) -> list[Item]:
    return list_with(ctx, source, options_for(source))


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    opts = options_for(source)
    sel = opts.get("detail_selector")
    if not sel or item.url.lower().split("?")[0].endswith(".pdf"):
        return item
    if opts.get("browser"):
        f = ctx.browser_get(item.url, wait_selector=sel)
    else:
        f = ctx.get(item.url)
    return fill_detail(item, f, sel)


# ───────────────────────────── presets (checked 4 Nov 2026) ─────────────────────────────
# Built-in options for the catalogue sources that use this parser; sources.yaml options override
# them key by key. Fixtures: tests/fixtures/<source id>/.
_EDA = "https://www.edaegypt.gov.eg/ar/التوعية/"
_EDA_TABLE = {"item_selector": "table tr", "title_selector": "td:nth-of-type(1)",
              "date_selector": "td:nth-of-type(2)", "link_selector": "a[href]"}
PRESETS: dict[str, dict] = {
    # EDA Egypt: tables "content | date | letter (PDF)"; English content on Arabic pages.
    "eda-eg": {"pages": [
        {**_EDA_TABLE, "doc_type": "dhpc",
         "url": _EDA + "منشورات-الإدارة-المركزية-للرعاية-الصيدلية/منشورات-اليقظة-الدوائية/"
                       "ثانيا-خطابات-التواصل-المباشر-مع-مقدمي-الرعاية-الصحية/"},
        {**_EDA_TABLE, "doc_type": "safety_alert",
         "url": _EDA + "منشورات-الإدارة-المركزية-للرعاية-الصيدلية/منشورات-اليقظة-الدوائية/"
                       "ثالثا-تنبيهات-السلامة/"},
        # Awareness letters (falsified / withdrawn products): "letter no. (n) of 2026 | mm/yyyy |
        # product"; the title is the letter link, the product goes to the summary.
        {"item_selector": "table tr", "title_selector": "td:nth-of-type(1) a",
         "date_selector": "td:nth-of-type(2)", "summary_selector": "td:nth-of-type(3)",
         "doc_type": "recall",
         "url": _EDA + "منشورات-السحب-والغش-الدوائي-خطابات-التوعية/خطابات-توعية/{year}/"},
    ]},
    # SFDA Saudi Arabia: warning cards (food and drug together) and the drug recall table.
    "sfda-sa": {"pages": [
        {"url": "https://www.sfda.gov.sa/ar/warnings", "item_selector": "div.node--type-warning",
         "title_selector": "p.head-subtitle", "date_selector": "div.text-primary span",
         "summary_selector": "p:not(.head-subtitle)", "tag_selector": "div.tag",
         "link_selector": "a[href*='/warnings/']", "id_attr": "data-history-node-id",
         "doc_type": "safety_alert"},
        {"url": "https://www.sfda.gov.sa/ar/drugs_circulars_withdrawal",
         "item_selector": "table tbody tr",
         "title_selector": "td[headers=view-field-name-product-table-column]",
         "date_selector": "time", "tag_selector": "td[headers=view-field-recall-action-table-column]",
         "link_selector": "a[href*='/drugs_circulars_withdrawal/']", "doc_type": "recall"},
    ]},
    # JFDA Jordan: latest circulars, "name | description | date dd/mm/yyyy | PDF".
    "jfda-jo": {"url": "https://www.jfda.jo/AR/List/أحدث_التعاميم_الصادرة",
                "item_selector": "tr.js-readMore-item", "title_selector": "td:nth-of-type(1)",
                "summary_selector": "td:nth-of-type(2)", "date_selector": "td:nth-of-type(3)",
                "link_selector": "a[href]", "doc_type": "safety_alert"},
    # UAE MOHAP: unreachable from here on 4 Nov 2026 (connection reset); no preset is guessed —
    # sources.yaml must give item_selector/link_pattern once the page has been seen.
}
