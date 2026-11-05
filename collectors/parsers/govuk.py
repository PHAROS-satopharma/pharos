"""MHRA on GOV.UK: Drug Safety Update and drug/device alerts (Atom feeds + the content API).

Lists from the Atom feed (``https://www.gov.uk/drug-safety-update.atom``,
``https://www.gov.uk/drug-device-alerts.atom``); details from
``https://www.gov.uk/api/content/<path>`` (body HTML, metadata, attachments).

Options:
  doc_type        str   default for every entry ('safety_update' for DSU, 'safety_alert' for alerts)
  alert_types     dict  metadata.alert_type → doc_type (defaults below)
  skip_alert_types list metadata.alert_type values whose detail is not fetched (default: devices)
"""

from __future__ import annotations

from urllib.parse import urlsplit

from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig, html_text,
                                     parse_date)
from collectors.parsers.feed import parse_feed

STRUCTURED_FIELDS: list[str] = []

CONTENT_API = "https://www.gov.uk/api/content"

ALERT_TYPES = {
    "medicines-recall": "recall",
    "medicines-recall-notification": "recall",
    "company-led-drugs": "recall",
    "drugs": "safety_alert",
    "medicines-notification": "safety_alert",
    "national-patient-safety": "safety_alert",
    # The monthly "MHRA Safety Roundup": since mid-2025 the letters sent to healthcare professionals
    # (DHPCs) are listed only in its body, which is read and screened in full.
    "mhra-safety-round-up": "newsletter",
    "devices": "other",
    "field-safety-notices": "other",
}

ATTACHMENT_MIMES = ("application/pdf", "application/vnd.openxmlformats", "application/msword")


def path_of(url: str) -> str:
    return urlsplit(url).path


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    fetched = ctx.get(source.url, accept="application/atom+xml")
    if fetched.status == 304:
        return []
    items = parse_feed(fetched.content, source, fetched.final_url)
    for item in items:
        item.external_id = path_of(item.url) or item.external_id  # stable GOV.UK base path
    return items


def apply_content(item: Item, data: dict, source: SourceConfig) -> Item:
    """Fill an Item from a GOV.UK content-API document. Pure: no network."""
    if not isinstance(data, dict) or "details" not in data:
        raise ParseError(f"GOV.UK content API changed shape for {item.url}")
    details = data.get("details") or {}
    metadata = details.get("metadata") or {}
    body = details.get("body") or ""
    if isinstance(body, list):  # multi-part bodies: [{content_type, content}]
        body = "\n".join(p.get("content", "") for p in body if "html" in p.get("content_type", ""))
    text = html_text(f"<main>{body}</main>") if body else ""
    description = (data.get("description") or "").strip()
    item.body_text = "\n\n".join(x for x in (description, text) if x) or item.body_text
    item.title = (data.get("title") or item.title).strip()
    item.published = (parse_date(metadata.get("issued_date"))
                      or parse_date(data.get("first_published_at")) or item.published)
    alert_type = metadata.get("alert_type")
    mapping = {**ALERT_TYPES, **(source.options.get("alert_types") or {})}
    if alert_type and alert_type in mapping:
        item.doc_type = mapping[alert_type]
    urls = []
    for att in details.get("attachments") or []:
        url = att.get("url")
        mime = (att.get("content_type") or "").lower()
        if url and mime.startswith(ATTACHMENT_MIMES) and url not in urls:
            urls.append(url)
    item.attachment_urls = urls[:8]
    item.structured = {
        **(item.structured or {}),
        "document_type": data.get("document_type"),
        "content_id": data.get("content_id"),
        "metadata": metadata,
        "first_published_at": data.get("first_published_at"),
        "public_updated_at": data.get("public_updated_at"),
        "locale": data.get("locale"),
    }
    if data.get("locale"):
        item.lang = data["locale"]
    return item


def fetch_detail(ctx: FetchContext, source: SourceConfig, item: Item) -> Item:
    path = path_of(item.url)
    if not path:
        return item
    fetched = ctx.get(f"{CONTENT_API}{path}", accept="application/json")
    if fetched.status != 200:
        return item
    try:
        data = fetched.json()
    except ValueError as exc:
        raise ParseError(f"GOV.UK content API returned non-JSON for {path}") from exc
    return apply_content(item, data, source)
