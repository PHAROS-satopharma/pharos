"""EMA direct healthcare professional communications (DHPC), from EMA's JSON data file.

Source: https://www.ema.europa.eu/en/documents/report/dhpc-output-json-report_en.json
(``{"meta": {...}, "data": [row, ...]}``; dates are dd/mm/yyyy). Every row is kept in
``Item.structured``; the active substances, medicine names and the nationally authorised medicines
named in the row are matched as structured fields (confidence 'high').

Options:
  categories   list  row categories to keep (default ["Human"])
  follow       bool  open the DHPC page for its text and the PDF (default true)

An EMA DHPC is an issue anchor (collectors/merge.py).
"""

from __future__ import annotations

from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig,
                                     attachment_links, dropped, html_text, parse_date, soup)

STRUCTURED_FIELDS = ["active_substances", "name_of_medicine",
                     "other_related_medicines_nationally_authorised", "referral_name"]

REQUIRED = {"name_of_medicine", "active_substances", "dhpc_url", "first_published_date"}


def split_list(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").replace("\n", ";").split(";") if p.strip()]


def title_for(row: dict) -> str:
    """EMA titles its DHPC pages "<medicine> - direct healthcare professional communication (DHPC)"."""
    name = (row.get("name_of_medicine") or "").strip() or (row.get("active_substances") or "").strip()
    return f"{name} - direct healthcare professional communication (DHPC)"


def parse_rows(data: dict, source: SourceConfig) -> list[Item]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError("EMA DHPC JSON has no 'data' list")
    if rows and not REQUIRED <= set(rows[0]):
        raise ParseError(f"EMA DHPC JSON changed shape: {sorted(rows[0])[:12]}")
    keep = {c.casefold() for c in source.options.get("categories", ["Human"])}
    items: list[Item] = []
    for row in rows:
        if keep and (row.get("category") or "").casefold() not in keep:
            # a veterinary letter: noted as dropped (filtered_item), never kept for a watched name
            dropped(title_for(row), f"category: {row.get('category') or 'none'}", unless_watched=False)
            continue
        url = (row.get("dhpc_url") or "").strip()
        if not url:
            continue
        structured = dict(row)
        structured["active_substances_list"] = split_list(row.get("active_substances"))
        structured["procedure_numbers"] = split_list(row.get("procedure_number"))
        items.append(Item(
            external_id=url,
            url=url,
            title=title_for(row),
            published=parse_date(row.get("dissemination_date")) or parse_date(
                row.get("first_published_date")),
            doc_type="dhpc",
            lang="en",
            structured=structured,
        ))
    return items


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    fetched = ctx.get(source.url, accept="application/json")
    if fetched.status == 304:
        return []
    try:
        data = fetched.json()
    except ValueError as exc:
        raise ParseError(f"EMA DHPC JSON did not parse: {exc}") from exc
    return parse_rows(data, source)


def fetch_detail(ctx: FetchContext, source: SourceConfig, item: Item) -> Item:
    if source.options.get("follow", True) is False:
        return item
    fetched = ctx.get(item.url)
    if fetched.status != 200 or not fetched.is_html:
        return item
    doc = soup(fetched)
    links = attachment_links(doc, fetched.final_url, selector="[data-section=documents]",
                             patterns=["/en/media/", "/en/documents/", ".pdf"])
    if not links:
        links = attachment_links(doc, fetched.final_url, patterns=["/en/documents/dhpc/", ".pdf"])
    item.attachment_urls = links[:4]
    text = html_text(doc, ".ema-node-content-wrapper")
    if text:
        item.body_text = text
    return item
