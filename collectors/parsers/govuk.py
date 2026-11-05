"""MHRA on GOV.UK: Drug Safety Update and drug/device alerts (Atom feeds + the content API).

Lists from the Atom feed (``https://www.gov.uk/drug-safety-update.atom``,
``https://www.gov.uk/drug-device-alerts.atom``); details from
``https://www.gov.uk/api/content/<path>`` (body HTML, metadata, attachments).

Options:
  doc_type        str   default for every entry ('safety_update' for DSU, 'safety_alert' for alerts)
  alert_types     dict  metadata.alert_type → doc_type (defaults below)
  skip_alert_types list metadata.alert_type values whose detail is not fetched (default: devices)
  roundup_days    int   how far back the Safety Roundups' letters are read (120; a backfill reads all)

The monthly "MHRA Safety Roundup" (``/drug-device-alerts/mhra-safety-roundup-<month>-<year>``) is
the only place MHRA lists the letters sent to healthcare professionals (DHPCs) since mid-2025: its
body section "Direct Healthcare Professional Communications" is one ``ul``, each ``li`` one letter
whose link is the letter PDF on assets.publishing.service.gov.uk ("Guanfacine prolonged-release
tablets (PL 49718/0136-0142): Important safety information …"; checked 5 Nov 2026). Each letter
becomes its own ``dhpc`` item, so it reaches review and matching by its own title; the roundup
stays one ``newsletter`` item.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from collectors.parsers._html_util import absolute, clean, keep, node_text
from collectors.parsers.base import (FetchContext, Item, ParseError, SourceConfig, html_text,
                                     parse_date, soup)
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

ROUNDUP = re.compile(r"/mhra-safety-roundup-[a-z]+-\d{4}/?$")
DHPC_HEADING = re.compile(r"direct healthcare professional communications?", re.I)

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
    days = int(source.options.get("roundup_days", 120))
    oldest = date.today() - timedelta(days=days)
    letters: list[Item] = []
    for item in items:
        if not ROUNDUP.search(path_of(item.url)):
            continue
        if not ctx.backfill and item.published and item.published < oldest:
            continue
        api = f"{CONTENT_API}{path_of(item.url)}"
        page = ctx.get(api, accept="application/json", raise_for_status=False)
        ctx.forget(api)                 # fetch_detail of a new roundup reads it again in full
        if page.status != 200:
            continue
        try:
            data = page.json()
        except ValueError as exc:
            raise ParseError(f"GOV.UK content API returned non-JSON for {item.url}") from exc
        letters.extend(roundup_letters(data, item, source))
    return items + letters


def roundup_letters(data: dict, roundup: Item, source: SourceConfig) -> list[Item]:
    """One ``dhpc`` Item per letter listed in a Safety Roundup's DHPC section. Pure: no network."""
    details = (data or {}).get("details") or {}
    body = details.get("body") or ""
    if isinstance(body, list):  # multi-part bodies: [{content_type, content}]
        body = "\n".join(p.get("content", "") for p in body if "html" in p.get("content_type", ""))
    if not body:
        return []
    doc = soup(f"<main>{body}</main>")
    heading = next((h for h in doc.find_all(["h2", "h3", "h4"]) if DHPC_HEADING.search(node_text(h))),
                   None)
    if heading is None:
        return []
    issued = (parse_date((details.get("metadata") or {}).get("issued_date"))
              or parse_date(data.get("first_published_at")) or roundup.published)
    name = clean(data.get("title")) or roundup.title
    out: list[Item] = []
    seen: set[str] = set()
    for el in heading.find_next_siblings():
        if el.name in ("h2", "h3", "h4"):
            break                       # the next section: medicine recalls, device notices
        for li in el.select("li") if el.name in ("ul", "ol") else []:
            a = li.select_one("a[href]")
            text = clean(node_text(li))
            title = clean(node_text(a)) if a is not None else text
            if not title:
                continue
            pdf = absolute(a["href"], roundup.url) if a is not None else ""
            key = pdf or f"{roundup.external_id}#dhpc-{len(out) + 1}"
            if key in seen or not keep(source, text):
                continue
            seen.add(key)
            out.append(Item(
                external_id=key, url=pdf or roundup.url, title=title, published=issued,
                doc_type="dhpc", lang=roundup.lang or "en",
                body_text=f"{text}\n\nListed in {name}: {roundup.url}",
                attachment_urls=[pdf] if pdf else [],
                structured={"roundup": roundup.url, "roundup_title": name}))
    return out


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
    if not path or (item.structured or {}).get("roundup"):  # a roundup letter: its PDF is the detail
        return item
    fetched = ctx.get(f"{CONTENT_API}{path}", accept="application/json")
    if fetched.status != 200:
        return item
    try:
        data = fetched.json()
    except ValueError as exc:
        raise ParseError(f"GOV.UK content API returned non-JSON for {path}") from exc
    return apply_content(item, data, source)
