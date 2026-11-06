"""Generic RSS / Atom parser (FDA MedWatch, BfArM Rote-Hand-Briefe, BASG, AEMPS, HSA, user feeds).

Options (sources.yaml ``options``):
  include_categories   list  keep an entry only if one of its categories equals one of these
                             (case-insensitive; ``domain:term`` also accepted, e.g. "Category:Product Recalls")
  include_keywords     list  keep only if the title or summary contains one of these
  exclude_keywords     list  drop if the title or summary contains one of these
  include_url_patterns list  keep only if the link contains one of these substrings
  exclude_url_patterns list  drop if the link contains one of these substrings
  doc_type             str   doc_type for every entry (default 'safety_alert')
  doc_type_rules       list  [{keyword|category|url: "...", doc_type: "..."}], first match wins
  lang                 str   language of the entries (default: the source's first language)
  follow               bool  fetch the entry page for body text and PDF links (default true)
  body_selector        str   CSS selector of the main text on the entry page
  attachment_selector  str   CSS selector holding the attachment links
  attachment_patterns  list  substrings marking attachment links (default: .pdf / BfArM blobs)
  max_attachments      int   default 6

An entry list that parses to nothing although the response is not a feed raises ParseError.
"""

from __future__ import annotations

from datetime import date

from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig, absolute,
                                     attachment_links, dropped, html_text, keyword_ok, parse_date,
                                     soup)

STRUCTURED_FIELDS: list[str] = []


def _categories(entry) -> list[str]:
    out: list[str] = []
    for tag in entry.get("tags") or []:
        term = (tag.get("term") or "").strip()
        if not term:
            continue
        out.append(term)
        scheme = (tag.get("scheme") or "").strip()
        if scheme:
            out.append(f"{scheme}:{term}")
    return out


def _published(entry) -> date | None:
    # The raw string first: feedparser's *_parsed tuples are converted to UTC, which moves
    # "Wed, 04 Nov 2026 00:00:00 +0800" (HSA) to 3 November. The regulator's own date is kept.
    for key in ("published", "updated", "dc_date", "created"):
        if entry.get(key):
            d = parse_date(entry[key])
            if d:
                return d
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return date(value.tm_year, value.tm_mon, value.tm_mday)
            except ValueError:
                continue
    return None


def _summary_text(entry) -> str:
    html = entry.get("summary") or ""
    if not html and entry.get("content"):
        html = entry["content"][0].get("value") or ""
    if not html.strip():
        return ""
    return html_text(f"<div>{html}</div>")


def _doc_type(opts: dict, title: str, cats: list[str], link: str) -> str:
    low_title, low_cats, low_link = title.casefold(), [c.casefold() for c in cats], link.casefold()
    for rule in opts.get("doc_type_rules") or []:
        if "keyword" in rule and rule["keyword"].casefold() in low_title:
            return rule["doc_type"]
        if "category" in rule and rule["category"].casefold() in low_cats:
            return rule["doc_type"]
        if "url" in rule and rule["url"].casefold() in low_link:
            return rule["doc_type"]
    return opts.get("doc_type", "safety_alert")


def parse_feed(content: bytes, source: SourceConfig, base_url: str) -> list[Item]:
    """Entries → Items, filtered by the source options. Pure: no network."""
    import feedparser

    parsed = feedparser.parse(content)
    version = parsed.get("version") or ""
    entries = parsed.get("entries") or []
    if not version and not entries:
        raise ParseError(f"{source.id}: response is not an RSS/Atom feed")
    opts = source.options
    inc_cats = {c.casefold() for c in opts.get("include_categories") or []}
    inc_urls = [p.casefold() for p in opts.get("include_url_patterns") or []]
    exc_urls = [p.casefold() for p in opts.get("exclude_url_patterns") or []]
    lang = source.lang or (parsed.feed.get("language") or "").split("-")[0].lower() or None
    items: list[Item] = []
    seen: set[str] = set()
    for entry in entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if link:
            link = absolute(link, base_url)
        if not title or not link:
            continue
        cats = _categories(entry)
        summary = _summary_text(entry)
        if inc_cats and not inc_cats & {c.casefold() for c in cats} and dropped(
                f"{title}\n{summary}", "categories: " + ", ".join(cats)[:120]):
            continue
        if not keyword_ok(f"{title}\n{summary}", opts.get("include_keywords"),
                          opts.get("exclude_keywords")):
            continue
        low_link = link.casefold()
        if inc_urls and not any(p in low_link for p in inc_urls):
            continue
        if any(p in low_link for p in exc_urls):
            continue
        external_id = (entry.get("id") or entry.get("guid") or link).strip()
        if external_id in seen:
            continue
        seen.add(external_id)
        items.append(Item(
            external_id=external_id, url=link, title=title, published=_published(entry),
            doc_type=_doc_type(opts, title, cats, link), lang=lang or None,
            body_text=summary or None,
            structured={"categories": cats, "summary": summary or None,
                        "feed_title": parsed.feed.get("title")},
        ))
    return items


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    fetched = ctx.get(source.url, accept="application/rss+xml, application/atom+xml, "
                                         "application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5")
    if fetched.status == 304:
        return []
    return parse_feed(fetched.content, source, fetched.final_url)


def fetch_detail(ctx: FetchContext, source: SourceConfig, item: Item) -> Item:
    opts = source.options
    if opts.get("follow", True) is False:
        return item
    fetched = ctx.get(item.url)
    if fetched.status != 200:
        return item
    if fetched.is_pdf:
        if item.url not in item.attachment_urls:
            item.attachment_urls.append(item.url)
        return item
    if not fetched.is_html:
        return item
    doc = soup(fetched)
    links = attachment_links(doc, fetched.final_url, selector=opts.get("attachment_selector"),
                             patterns=opts.get("attachment_patterns"))
    text = html_text(doc, opts.get("body_selector"))
    if text:
        item.body_text = text
    limit = int(opts.get("max_attachments", 6))
    for url in links[:limit]:
        if url not in item.attachment_urls:
            item.attachment_urls.append(url)
    return item
