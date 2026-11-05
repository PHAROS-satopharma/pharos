"""US drug recalls from the openFDA enforcement endpoint (``https://api.fda.gov/drug/enforcement.json``).

Reads reports by ``report_date`` for the last ``lookback_days`` (default 45), or the whole backfill
window, 100 at a time (openFDA allows ``skip`` up to 25,000). openFDA answers 404 "No matches
found" for an empty window — that is a genuine empty result. ``OPENFDA_API_KEY`` raises the daily
quota when present.

Options:
  lookback_days  int  default 45
  page_size      int  default 100

The API has no page per recall; the item URL is the API query for that recall number, which returns
exactly the record stored in ``document.structured``.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date, timedelta
from urllib.parse import quote

from collectors.parsers.base import FetchContext, Item, ParseError, SourceConfig, parse_date

STRUCTURED_FIELDS = ["openfda.generic_name", "openfda.substance_name", "openfda.brand_name",
                     "product_description"]

MAX_SKIP = 25000


def _window(ctx: FetchContext, source: SourceConfig, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    if ctx.backfill:
        months = int(getattr(ctx, "backfill_months", 12) or 12)
        return today - timedelta(days=31 * months), today
    return today - timedelta(days=int(source.options.get("lookback_days", 45))), today


def record_to_item(rec: dict, base_url: str) -> Item:
    number = (rec.get("recall_number") or "").strip()
    product = " ".join((rec.get("product_description") or "").split())
    if number:
        external_id, link = number, f"{base_url}?search=recall_number:%22{quote(number)}%22"
    else:
        # openFDA publishes some records with a blank recall_number (e.g. event 100061, Oct 2026).
        # The event id plus the product text identifies the record and stays the same between runs.
        event = (rec.get("event_id") or "").strip()
        if not event or not product:
            raise ParseError("openFDA enforcement record without recall_number or event_id")
        digest = hashlib.sha256(product.encode("utf-8")).hexdigest()[:12]
        external_id, link = f"event-{event}-{digest}", f"{base_url}?search=event_id:%22{quote(event)}%22"

    body = "\n".join(x for x in (
        rec.get("product_description"), f"Reason for recall: {rec.get('reason_for_recall', '')}",
        f"Recalling firm: {rec.get('recalling_firm', '')}", f"Classification: {rec.get('classification', '')}",
        f"Code info: {rec.get('code_info', '')}", f"Distribution: {rec.get('distribution_pattern', '')}",
    ) if x and x.split(":")[-1].strip())
    return Item(
        external_id=external_id,
        url=link,
        title=product[:300] + ("…" if len(product) > 300 else ""),
        published=parse_date(rec.get("report_date")) or parse_date(rec.get("recall_initiation_date")),
        doc_type="recall",
        lang="en",
        body_text=body,
        structured=rec,
    )


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    start, end = _window(ctx, source)
    size = int(source.options.get("page_size", 100))
    key = os.environ.get("OPENFDA_API_KEY")
    base = source.url.split("?")[0]
    items: list[Item] = []
    skip = 0
    while True:
        query = (f"{base}?search=report_date:[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
                 f"&sort=report_date:desc&limit={size}&skip={skip}")
        if key:
            query += f"&api_key={key}"
        fetched = ctx.get(query, accept="application/json", raise_for_status=False)
        if fetched.status == 404:
            break  # "No matches found"
        if fetched.status != 200:
            from collectors.core.context import FetchError

            raise FetchError(fetched.status, base)
        try:
            data = fetched.json()
        except ValueError as exc:
            raise ParseError(f"openFDA returned non-JSON: {exc}") from exc
        results = data.get("results")
        if not isinstance(results, list):
            raise ParseError("openFDA enforcement response has no results list")
        items.extend(record_to_item(r, base) for r in results)
        total = int(((data.get("meta") or {}).get("results") or {}).get("total") or 0)
        skip += size
        if not results or skip >= total or skip > MAX_SKIP:
            break
    return items
