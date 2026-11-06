"""PHAROS — Medsafe (New Zealand): DHCP letters and safety communications.

Two sources share this module; ``options.page`` says which page ``source.url`` is.

``page: dhcp`` — ``medsafe-dhcp``, ``https://www.medsafe.govt.nz/safety/DHCPLetters.asp``.
  A table with ``th`` headers Date sent | Product | Reason. Product holds
  ``a[href="DHCPLetters/<name>.pdf"]`` (relative) and a "(PDF, 2 pages, 607 KB)" note; Date sent is
  "29 September 2026". Title = Reason (the subject as published, which names product and
  substance); the product link text goes to ``structured``. The item URL is the PDF. doc_type
  ``dhpc``.

``page: comms`` — ``medsafe-comms``, ``https://www.medsafe.govt.nz/safety/SafetyCommunications.asp``.
  A table Date | Communication (Alert / Monitoring) | Product Type (Medicine / Device / …) | Topic
  (``a[href="Alerts/<slug>.asp"]``). Only Product Type "Medicine" is kept unless
  ``include_product_types`` says otherwise. Alert → ``safety_alert``, Monitoring → ``signal``.
  Detail body: ``#content-area``.

(checked 4 Nov 2026)

``page: prescriber`` — ``medsafe-prescriber-update``, ``https://www.medsafe.govt.nz/profs/PUArticles.asp``,
  the latest issue of Prescriber Update (quarterly: March, June, September, December; checked 6 Nov
  2026). Medsafe has no feed for it. In ``#content-area``: ``p.updated`` "Revised: 3 September 2026",
  the issue PDF ``a[href*="PUArticles/PDF/"]`` "Download the latest issue of Prescriber Update –
  September 2026", and ``ul li a[href="PUArticles/September2026/<slug>.html"]``, one per article. One
  item per article and one for the issue PDF, all ``newsletter``. Published = the "Revised" day when it
  falls in the issue's month, else the 1st of that month; an article page's own "Published: 3 September
  2026" (``p.updated``) replaces it when the article is opened. Detail body ``#content-area``.

Options: ``page`` (``dhcp`` | ``comms`` | ``prescriber``; default guessed from the URL),
``include_product_types`` (``["Medicine"]``), ``include_keywords`` / ``exclude_keywords``, ``lang`` (``en``).
"""

from __future__ import annotations

import re

from collectors.parsers._html_util import (absolute, column, fill_detail, keep, local_date,
                                           node_text, require, table_records)
from collectors.parsers.base import Item, SourceConfig, soup

_PUBLISHED = re.compile(r"(?:Published|Revised)\s*:?\s*(.+)", re.I)
_DOWNLOAD = re.compile(r"^Download the latest issue of\s+", re.I)


def page_kind(source: SourceConfig) -> str:
    kind = (source.options or {}).get("page")
    if kind:
        return str(kind).lower()
    url = source.url.lower()
    if "puarticles" in url:
        return "prescriber"
    return "dhcp" if "dhcp" in url else "comms"


def parse_dhcp(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "en"
    items: list[Item] = []
    seen: set[str] = set()
    for table in doc.select("table"):
        for tds, header in table_records(table, ("date sent", "product", "reason")):
            idate = column(header, "date", default=0)
            iprod = column(header, "product", default=1)
            ireason = column(header, "reason", default=2)
            if max(idate, iprod, ireason) >= len(tds):
                continue
            a = tds[iprod].select_one("a[href]")
            if a is None:
                continue
            url = absolute(a["href"], base_url)
            product = node_text(a)
            reason = node_text(tds[ireason])
            title = reason or product
            if url in seen or not title or not keep(source, title, product):
                continue
            seen.add(url)
            items.append(Item(
                external_id=url, url=url, title=title,
                published=local_date(node_text(tds[idate]), lang), doc_type="dhpc", lang=lang,
                body_text="\n".join(x for x in (product, reason) if x), attachment_urls=[url],
                structured={"product": product}))
    return items


def parse_comms(html, base_url: str, source: SourceConfig) -> list[Item]:
    doc = soup(html)
    lang = source.lang or "en"
    types = {t.casefold() for t in (source.options or {}).get("include_product_types",
                                                             ["Medicine"]) or []}
    items: list[Item] = []
    seen: set[str] = set()
    for table in doc.select("table"):
        for tds, header in table_records(table, ("communication", "product type", "topic")):
            if "topic" not in " ".join(header):
                continue
            idate = column(header, "date", default=0)
            ikind = column(header, "communication", default=1)
            itype = column(header, "product type", default=2)
            itopic = column(header, "topic", default=3)
            if max(idate, ikind, itype, itopic) >= len(tds):
                continue
            ptype = node_text(tds[itype])
            if types and ptype.casefold() not in types:
                continue
            a = tds[itopic].select_one("a[href]")
            if a is None:
                continue
            url = absolute(a["href"], base_url)
            title = node_text(a)
            kind = node_text(tds[ikind])
            if url in seen or not title or not keep(source, title):
                continue
            seen.add(url)
            items.append(Item(
                external_id=url, url=url, title=title,
                published=local_date(node_text(tds[idate]), lang),
                doc_type="signal" if kind.casefold().startswith("monitor") else "safety_alert",
                lang=lang, structured={"communication": kind, "product_type": ptype}))
    return items


def _stamp(area, lang: str):
    """The date of a "Published: 3 September 2026" / "Revised: …" line, or None."""
    m = _PUBLISHED.search(node_text(area.select_one("p.updated")) if area is not None else "")
    return local_date(m.group(1), lang) if m else None


def parse_prescriber(html, base_url: str, source: SourceConfig) -> list[Item]:
    """The latest Prescriber Update: its articles and the issue PDF."""
    doc = soup(html)
    lang = source.lang or "en"
    area = doc.select_one("#content-area")
    pdf = next((a for a in area.select("a[href]")
                if "/pdf/" in a["href"].lower() and a["href"].lower().endswith(".pdf")
                and node_text(a)), None) if area is not None else None
    if pdf is None:
        return []          # not the latest-issue page any more: list_items raises ParseError
    # "Download the latest issue of Prescriber Update – September 2026" → "Prescriber Update – September 2026"
    issue_title = _DOWNLOAD.sub("", node_text(pdf))
    issue = local_date(issue_title, lang)
    revised = _stamp(area, lang)
    published = revised if revised and issue and (revised.year, revised.month) == (
        issue.year, issue.month) else (issue or revised)
    items: list[Item] = []
    seen: set[str] = set()
    for a in area.select("ul li a[href]"):
        title = node_text(a)
        url = absolute(a["href"], base_url)
        if not title or url in seen or not keep(source, title):
            continue
        seen.add(url)
        items.append(Item(
            external_id=url, url=url, title=title, published=published, doc_type="newsletter",
            lang=lang, structured={"issue": issue_title or None}))
    url = absolute(pdf["href"], base_url)
    if keep(source, issue_title, *(i.title for i in items)):
        items.append(Item(
            external_id=url, url=url, title=issue_title, published=published, doc_type="newsletter",
            lang=lang, body_text="\n".join(i.title for i in items), attachment_urls=[url],
            structured={"issue": issue_title, "articles": [i.url for i in items]}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    f = ctx.get(source.url)
    if f.status == 304:
        return []
    kind = page_kind(source)
    if kind == "prescriber":
        items = parse_prescriber(f, f.final_url, source)
        require(items or soup(f).select("#content-area a[href*='PUArticles/PDF/']"), f,
                marker="content-area")
        return items
    if kind == "dhcp":
        items = parse_dhcp(f, f.final_url, source)
    else:
        items = parse_comms(f, f.final_url, source)
    require(items or soup(f).select("table td a[href]"), f, marker="<table")
    return items


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    if item.url.lower().split("?")[0].endswith(".pdf"):
        return item
    f = ctx.get(item.url)
    item = fill_detail(item, f, "#content-area", patterns=(".pdf",))
    if page_kind(source) == "prescriber" and f.status == 200 and f.content:
        published = _stamp(soup(f).select_one("#content-area"), item.lang or source.lang or "en")
        if published:
            item.published = published
    return item
