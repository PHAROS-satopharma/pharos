"""PHAROS — Emirates Drug Establishment (EDE, UAE) news, in Arabic and in English.

Source: ``uae-ede``. EDE took over medicines regulation from the Ministry of Health and Prevention
(MOHAP); mohap.gov.ae resets every connection from outside the UAE (``uae-mohap`` stays off), while
ede.gov.ae answers a plain request, from GitHub's runners too (probe, 5 Nov 2026).

Lists (12 items each, newest first, server-rendered Liferay):

* ``https://www.ede.gov.ae/ar/news`` — Arabic, the official language;
* ``https://www.ede.gov.ae/en/news`` — the same news in English.

Page structure relied on (checked 5 Nov 2026): a card ``div.col-lg-4`` holding links to the article
``/w/<slug>`` (picture, "Published <date>" block and "Read more" all link to it). Inside the card:
``[data-lfr-editable-id=element-date]`` = the date ("Wednesday, 04 November 2026" /
"الأربعاء, ٠٤ نوفمبر ٢٠٢٦"); the title is the ``element-text`` three levels under the link (the
"Published" / "تاريخ النشر" label is four levels under it).

Both lists link to the bare ``/w/<slug>``, which opens in Arabic. Each item's link is rewritten to
its own language (``/ar/w/<slug>``, ``/en/w/<slug>``, both served), so the Arabic and English copies
of one news item are two notices, each screened in its own language.

Most items are corporate news; the regulatory ones are typed by ``DOC_TYPE_RULES`` (recall / ban /
warning), the rest are ``other``. Detail body: ``[data-lfr-editable-id=element-html]``.

Options: ``pages`` (``[{url, lang}]``, default ``PAGES``); any ``generic_html`` option overrides.
"""

from __future__ import annotations

import re

from collectors.parsers import generic_html
from collectors.parsers.base import Item, SourceConfig

PAGES = [{"url": "https://www.ede.gov.ae/ar/news", "lang": "ar"},
         {"url": "https://www.ede.gov.ae/en/news", "lang": "en"}]

DOC_TYPE_RULES = [
    {"match": r"\brecall|\bwithdraw|سحب|استدعاء", "doc_type": "recall"},
    {"match": r"\bbans?\b|\bwarn|\balert|\bsafety\b|تحظر|حظر|تحذر|تحذير|سلامة", "doc_type": "safety_alert"},
]

OPTIONS = {
    "item_selector": 'div.col-lg-4:has(a[href*="/w/"])',
    "link_pattern": r"/w/[^/?#]+",
    "title_selector": "a > div > div > [data-lfr-editable-id=element-text]",
    "date_selector": "[data-lfr-editable-id=element-date]",
    "detail_selector": "[data-lfr-editable-id=element-html]",
    "doc_type": "other",
    "doc_type_rules": DOC_TYPE_RULES,
    "item_lang_detect": False,
}

_ARTICLE = re.compile(r"^(https://www\.ede\.gov\.ae)/(?:(?:ar|en)/)?w/")


def options_for(source: SourceConfig) -> dict:
    opts = dict(OPTIONS)
    opts.update(source.options or {})
    return opts


def in_language(url: str, lang: str) -> str:
    """``https://www.ede.gov.ae/w/<slug>`` → ``https://www.ede.gov.ae/<lang>/w/<slug>``."""
    return _ARTICLE.sub(rf"\1/{lang}/w/", url, count=1)


def list_items(ctx, source: SourceConfig) -> list[Item]:
    opts = options_for(source)
    out: list[Item] = []
    for page in opts.get("pages") or PAGES:
        lang = page.get("lang") or source.lang
        page_opts = {k: v for k, v in opts.items() if k != "pages"} | page | {"lang": lang}
        for it in generic_html.list_with(ctx, source, page_opts):
            it.url = in_language(it.url, lang)
            it.external_id = it.url
            out.append(it)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return generic_html.fill_detail(item, ctx.get(item.url), options_for(source)["detail_selector"])
