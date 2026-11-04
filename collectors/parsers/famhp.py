"""PHAROS — AFMPS / FAGG / FAMHP (Belgium) news, read with the headless browser.

Source: ``famhp-news``; ``source.url``: ``https://www.afmps.be/fr/news`` (Dutch: ``https://www.fagg.be/nl/news``;
both languages are listed with ``urls``).

On 4 Nov 2026 a plain HTTP request answered an F5 "TSPD" JavaScript interstitial (saved as
``tests/fixtures/famhp-news/challenge_fr.html``), so the source is ``channel: browser``. The parser
never tries to get past a challenge: if the page the browser ends on is still the interstitial
(``TSPD`` / ``bobcmn`` markers, or any marker ``FetchContext`` knows), it raises ``SourceBlocked`` and
the source health becomes ``blocked``.

Page structure relied on: the live listing could not be seen from here, so the parser uses link
mode of ``generic_html``: every link to an article ``/<lang>/news/<slug>`` is one item; the date is
the first date near the link ("04/11/2026" or "4 novembre 2026"). Items whose title has a safety
word are ``safety_alert``; titles with « DHPC » / « communication directe » are ``dhpc``; « rappel » /
« terugroeping » are ``recall``; others ``other`` (the matcher still screens every one).

Options: ``urls`` (``{lang: url}``), ``link_pattern``, ``wait_selector`` (``main a[href*='/news/']``),
``detail_selector`` (``main``), ``include_keywords`` / ``exclude_keywords``.
"""

from __future__ import annotations

import re

from collectors.parsers import generic_html
from collectors.parsers.base import Item, SourceBlocked, SourceConfig

_INTERSTITIAL = re.compile(r"/TSPD/|bobcmn|window\[\"bobcmn\"\]", re.I)
_LANG = re.compile(r"/(fr|nl|de|en)/")

DOC_TYPE_RULES = [
    {"match": r"\bDHPC\b|communication directe|directe communicatie", "doc_type": "dhpc"},
    {"match": r"rappel|terugroep|recall", "doc_type": "recall"},
    {"match": r"sécurité|risque|veiligheid|risico|pharmacovigilan|farmacovigilan|"
              r"effets indésirables|bijwerking", "doc_type": "safety_alert"},
]


def options_for(source: SourceConfig, lang: str, url: str) -> dict:
    opts = dict(source.options or {})
    opts.setdefault("browser", True)
    opts.setdefault("link_pattern", rf"/{lang}/news/[^/?#]+/?$")
    opts.setdefault("wait_selector", "a[href*='/news/']")
    opts.setdefault("detail_selector", "main")
    opts.setdefault("doc_type_rules", DOC_TYPE_RULES)
    opts.setdefault("doc_type", "other")
    opts["lang"] = lang
    opts["url"] = url
    opts.pop("urls", None)
    opts.pop("extra_urls", None)
    return opts


def targets(source: SourceConfig) -> list[tuple[str, str]]:
    urls = (source.options or {}).get("urls")
    if isinstance(urls, dict) and urls:
        return list(urls.items())
    m = _LANG.search(source.url)
    return [(m.group(1) if m else (source.lang or "fr"), source.url)]


def check_not_interstitial(fetched) -> None:
    head = fetched.text[:20000] if fetched.content else ""
    if _INTERSTITIAL.search(head):
        raise SourceBlocked(f"F5 interstitial at {fetched.final_url}; not attempted further")


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    for lang, url in targets(source):
        opts = options_for(source, lang, url)
        f = generic_html.read_page(ctx, url, opts)   # ctx raises SourceBlocked on known challenges
        check_not_interstitial(f)
        got = generic_html.extract(f, f.final_url, source, opts)
        generic_html.require(got or generic_html.raw_nodes(f, opts), f, marker="/news/")
        out.extend(got)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    opts = options_for(source, item.lang or "fr", source.url)
    f = ctx.browser_get(item.url, wait_selector=opts["detail_selector"])
    check_not_interstitial(f)
    return generic_html.fill_detail(item, f, opts["detail_selector"])
