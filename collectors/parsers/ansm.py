"""PHAROS — ANSM (France) « Informations de sécurité ».

Source: ``ansm-securite``; ``source.url`` is the list, normally filtered to medicines:
``https://ansm.sante.fr/informations-de-securite/?safety_news_filter[healthProducts][]=20``
(20 Médicaments; 21, 22 and 25 are the other product families).

Page structure relied on (checked 4 Nov 2026):

* list: ``article.article-item > a[href]`` holding ``span.article-category`` (RISQUES MEDICAMENTEUX,
  RAPPEL DE PRODUIT, DEFAUT QUALITE, INFORMATION AUX UTILISATEURS…), ``span.article-health-product``,
  ``span.article-date`` ("PUBLIÉ LE 04/11/2026"), ``span.article-title`` and ``span.article-content``.
  Further pages: ``&page=2``…
* detail: ``h1.page-header-title``, body ``div.wysiwyg-content``, originals under ``/uploads/…pdf``.

Options:

* ``include_categories`` — list of category labels to keep (upper-case as shown); default all.
* ``include_keywords`` / ``exclude_keywords`` — on title + summary.
* ``max_pages`` (1) / ``backfill_pages`` (5).
* ``lang`` — default ``fr``.
"""

from __future__ import annotations

from collectors.parsers._html_util import (absolute, clean, fill_detail, keep, local_date,
                                           node_text, pages_to_read, require)
from collectors.parsers.base import Item, SourceConfig, soup

# Category label → doc_type. Titles announcing a letter to professionals are DHPCs.
CATEGORY_DOC_TYPE = {
    "RISQUES MEDICAMENTEUX": "safety_alert",
    "RISQUES MÉDICAMENTEUX": "safety_alert",
    "RAPPEL DE PRODUIT": "recall",
    "DEFAUT QUALITE": "recall",
    "DÉFAUT QUALITÉ": "recall",
    "INFORMATION AUX UTILISATEURS": "safety_update",
    "RUPTURE DE STOCK": "other",
}
_DHPC_HINTS = ("lettre aux professionnels", "dhpc", "lettre aux prescripteurs")


def _page_url(url: str, page: int) -> str:
    if page <= 1:
        return url
    return f"{url}{'&' if '?' in url else '?'}page={page}"


def parse_list(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    wanted = {c.upper() for c in (source.options or {}).get("include_categories") or []}
    lang = source.lang or "fr"
    items: list[Item] = []
    for art in doc.select("article.article-item"):
        a = art.select_one("a[href]")
        if a is None:
            continue
        category = node_text(art.select_one("span.article-category")).upper()
        if wanted and category not in wanted:
            continue
        title = node_text(art.select_one("span.article-title")) or clean(a.get("title"))
        summary = node_text(art.select_one("span.article-content"))
        if not title or not keep(source, title, summary):
            continue
        url = absolute(a["href"], base_url)
        doc_type = CATEGORY_DOC_TYPE.get(category, "other")
        if doc_type == "safety_alert" and any(h in (title + " " + summary).casefold()
                                              for h in _DHPC_HINTS):
            doc_type = "dhpc"
        items.append(Item(
            external_id=url, url=url, title=title,
            published=local_date(node_text(art.select_one("span.article-date")), lang),
            doc_type=doc_type, lang=lang, body_text=summary or None,
            structured={"category": category or None,
                        "health_product": node_text(art.select_one("span.article-health-product"))
                        or None}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    out: list[Item] = []
    for page in range(1, pages_to_read(ctx, source) + 1):
        f = ctx.get(_page_url(source.url, page))
        if f.status == 304:
            break
        doc_items = parse_list(f, f.final_url, source)
        if page == 1:
            require(soup(f).select("article.article-item"), f, marker="article-list",
                    empty_markers=("Aucun résultat", "Aucune information"))
        if not doc_items and page > 1:
            break
        out.extend(doc_items)
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "div.wysiwyg-content")
