"""Health Canada recalls and safety alerts (open-data JSON, read daily).

Source: https://recalls-rappels.canada.ca/sites/default/files/opendata-donneesouvertes/HCRSAMOpenData.json
— a flat list of every recall and alert on recalls-rappels.canada.ca (vehicles, food, consumer
products, devices, drugs). Only health products are kept.

Options:
  include_organizations  list  default ["Drugs and health products", "Marketed health products"]
  exclude_categories     list  default ["Veterinary drugs"]
  alert_organizations    list  organizations whose rows are advisories rather than recalls
                               (default ["Marketed health products"] → doc_type 'safety_alert')
  follow                 bool  open the notice page for its full text (default true)

The open-data file carries the English record only; the French notice is linked from the English
page and is not listed separately.
"""

from __future__ import annotations

import html as htmllib

from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig,
                                     attachment_links, html_text, parse_date, soup)

STRUCTURED_FIELDS = ["Product"]

REQUIRED = {"NID", "Title", "URL", "Organization", "Category", "Last updated"}


def _clean(value: str | None) -> str:
    return " ".join(htmllib.unescape(value or "").replace("​", "").split())


def parse_records(rows: list, source: SourceConfig) -> list[Item]:
    if not isinstance(rows, list):
        raise ParseError("Health Canada open data is not a list")
    if rows and not REQUIRED <= set(rows[0]):
        raise ParseError(f"Health Canada open data changed shape: {sorted(rows[0])[:12]}")
    opts = source.options
    orgs = {o.casefold() for o in opts.get("include_organizations",
                                          ["Drugs and health products", "Marketed health products"])}
    excl = {c.casefold() for c in opts.get("exclude_categories", ["Veterinary drugs"])}
    alerts = {o.casefold() for o in opts.get("alert_organizations", ["Marketed health products"])}
    items: list[Item] = []
    for row in rows:
        org = (row.get("Organization") or "").strip()
        if org.casefold() not in orgs or (row.get("Category") or "").casefold() in excl:
            continue
        url = (row.get("URL") or "").replace("\\/", "/").strip()
        nid = str(row.get("NID") or "").strip()
        if not url or not nid:
            continue
        body = "\n".join(x for x in (
            _clean(row.get("Product")), _clean(row.get("Issue")),
            _clean(row.get("What you should do"))) if x)
        items.append(Item(
            external_id=nid, url=url, title=_clean(row.get("Title")),
            published=parse_date(row.get("Last updated")),
            doc_type="safety_alert" if org.casefold() in alerts else "recall",
            lang="fr" if "/fr/" in url else "en",
            body_text=body or None, structured=dict(row),
        ))
    return items


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    fetched = ctx.get(source.url, accept="application/json")
    if fetched.status == 304:
        return []
    try:
        rows = fetched.json()
    except ValueError as exc:
        raise ParseError(f"Health Canada open data did not parse: {exc}") from exc
    return parse_records(rows, source)


def fetch_detail(ctx: FetchContext, source: SourceConfig, item: Item) -> Item:
    if source.options.get("follow", True) is False:
        return item
    fetched = ctx.get(item.url)
    if fetched.status != 200 or not fetched.is_html:
        return item
    doc = soup(fetched)
    item.attachment_urls = attachment_links(doc, fetched.final_url)[:4]
    text = html_text(doc, "main")
    if text:
        item.body_text = text
    return item
