"""EMA periodic safety update report single assessments (PSUSA), from EMA's JSON data file.

Source: https://www.ema.europa.eu/en/documents/report/medicines-output-periodic_safety_update_report_single_assessments-output-json-report_en.json
(about 2,750 rows; the whole history is listed every time, so the backfill takes all of it).
Rows carry ``active_substance`` (``;``-separated) and ``active_substances_in_scope_of_procedure``;
both are matched as structured fields (confidence 'high'). The PSUSA page is opened only for rows
that matched (sources.yaml ``detail: matched_only``), which keeps a backfill to a few requests.

Options:
  categories   list  row categories to keep (default ["Human"])

The title is composed from the row, since the JSON carries none:
``<substances in scope>: PSUSA/00001911/202412 (Maintenance)``.
"""

from __future__ import annotations

from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig,
                                     attachment_links, html_text, parse_date, soup)
from collectors.parsers.ema_dhpc import split_list

STRUCTURED_FIELDS = ["active_substance", "active_substances_in_scope_of_procedure",
                     "related_medicines"]

REQUIRED = {"active_substance", "procedure_number", "regulatory_outcome", "first_published_date",
            "psusa_url"}


def title_for(row: dict) -> str:
    scope = (row.get("active_substances_in_scope_of_procedure") or row.get("active_substance")
             or "").strip()
    outcome = (row.get("regulatory_outcome") or "").strip()
    title = f"{scope}: {row.get('procedure_number', '').strip()}"
    return f"{title} ({outcome})" if outcome else title


def parse_rows(data: dict, source: SourceConfig) -> list[Item]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ParseError("EMA PSUSA JSON has no 'data' list")
    if rows and not REQUIRED <= set(rows[0]):
        raise ParseError(f"EMA PSUSA JSON changed shape: {sorted(rows[0])[:12]}")
    keep = {c.casefold() for c in source.options.get("categories", ["Human"])}
    items: list[Item] = []
    seen: set[str] = set()
    for row in rows:
        if keep and (row.get("category") or "").casefold() not in keep:
            continue
        procedure = (row.get("procedure_number") or "").strip()
        if not procedure or procedure in seen:
            continue
        seen.add(procedure)
        structured = dict(row)
        structured["active_substances_list"] = split_list(row.get("active_substance"))
        structured["procedure_numbers"] = [procedure]
        items.append(Item(
            external_id=procedure,
            url=(row.get("psusa_url") or "").strip() or source.url,
            title=title_for(row),
            published=parse_date(row.get("first_published_date")),
            doc_type="psusa",
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
        raise ParseError(f"EMA PSUSA JSON did not parse: {exc}") from exc
    return parse_rows(data, source)


def fetch_detail(ctx: FetchContext, source: SourceConfig, item: Item) -> Item:
    if not item.url.startswith("https://www.ema.europa.eu/"):
        return item
    fetched = ctx.get(item.url)
    if fetched.status != 200 or not fetched.is_html:
        return item
    doc = soup(fetched)
    item.attachment_urls = attachment_links(
        doc, fetched.final_url, selector="[data-section=documents]",
        patterns=["/en/media/", "/en/documents/", ".pdf"])[:4]
    text = html_text(doc, ".ema-node-content-wrapper")
    if text:
        item.body_text = text
    return item
