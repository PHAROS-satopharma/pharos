"""MHRA on GOV.UK: Drug Safety Update and drug/device alerts (the search API + the content API).

Lists from GOV.UK's search API (``https://www.gov.uk/api/search.json?filter_organisations=medicines-and-
healthcare-products-regulatory-agency&filter_format=medical_safety_alert`` or ``drug_safety_update``),
newest first, 100 a page; details from ``https://www.gov.uk/api/content/<path>`` (body HTML, metadata,
attachments). The Atom feeds read until 6 November 2026 (``…/drug-device-alerts.atom``) hold only the
newest 20 entries and cannot page: what dropped off between two reads was lost for good (the Safety
Roundups of November 2025 to June 2026, the Class 4 levetiracetam defect notice of 1 October 2026), and
a backfill could not reach anything older. The search API lists every item (1,465 alerts and 871 updates
on 6 November 2026). A run reads back to two weeks before the last complete read; a first read takes the
newest page; a backfill reads the whole list. An Atom ``url`` is still read as a feed.

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
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from collectors.parsers._html_util import absolute, clean, keep, node_text
from collectors.parsers.base import (FetchContext, Item, ParseError, SourceBlocked, SourceConfig,
                                     html_text, parse_date, soup)
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


SEARCH_FIELDS = "title,link,public_timestamp,description,alert_type"
PAGE = 100
MAX_PAGES = 40              # 4,000 items: the whole list is 1,465 alerts (6 Nov 2026)
OVERLAP = timedelta(days=14)


def path_of(url: str) -> str:
    return urlsplit(url).path


def is_search(source: SourceConfig) -> bool:
    return "/api/search.json" in source.url


def search_url(source: SourceConfig, start: int) -> str:
    sep = "&" if "?" in source.url else "?"
    return f"{source.url}{sep}order=-public_timestamp&count={PAGE}&start={start}&fields={SEARCH_FIELDS}"


def _timestamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def search_item(row: dict, source: SourceConfig) -> Item | None:
    """One Item from a search-API result. Pure: no network."""
    link, title = row.get("link") or "", clean(row.get("title"))
    if not link.startswith("/") or not title:
        return None
    alert = row.get("alert_type")
    alert = alert[0] if isinstance(alert, list) and alert else alert
    mapping = {**ALERT_TYPES, **(source.options.get("alert_types") or {})}
    doc_type = mapping.get(alert) if isinstance(alert, str) else None
    return Item(external_id=link, url=f"https://www.gov.uk{link}", title=title,
                published=parse_date(row.get("public_timestamp")),
                doc_type=doc_type or source.options.get("doc_type", "other"),
                lang=(source.languages or ["en"])[0], body_text=clean(row.get("description")) or None)


def list_search(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    """The search API's list, newest first: back to two weeks before the last complete read (the newest
    page on a first read), or all of it in a backfill."""
    last_ok = getattr(ctx, "last_ok_at", None)
    back_to = last_ok - OVERLAP if isinstance(last_ok, datetime) else None
    items: list[Item] = []
    for page in range(MAX_PAGES):
        url = search_url(source, page * PAGE)
        ctx.forget(url)                     # always the full page: the API answers in one request
        fetched = ctx.get(url, accept="application/json")
        try:
            data = fetched.json()
        except ValueError as exc:
            raise ParseError(f"GOV.UK search API returned non-JSON for {url}") from exc
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise ParseError("GOV.UK search API changed shape: no results list")
        for row in results:
            item = search_item(row, source) if isinstance(row, dict) else None
            if item is not None and keep(source, item.title, item.body_text):
                items.append(item)
        total = data.get("total")
        if len(results) < PAGE or (isinstance(total, int) and (page + 1) * PAGE >= total):
            break
        if not ctx.backfill:
            stamps = [t for t in (_timestamp(r.get("public_timestamp")) for r in results
                                  if isinstance(r, dict)) if t is not None]
            if back_to is None or not stamps or min(stamps) < back_to:
                break
    else:
        errors = getattr(ctx, "list_errors", None)
        if errors is not None:
            errors.append(f"GOV.UK search: more than {MAX_PAGES * PAGE} items, the oldest were not listed")
    return items


def list_items(ctx: FetchContext, source: SourceConfig) -> list[Item]:
    if is_search(source):
        items = list_search(ctx, source)
    else:
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
        try:
            letters.extend(read_roundup(ctx, item, source))
        except SourceBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - one roundup not read never loses the feed
            # The feed's alerts and updates are kept; the roundup is read again on the next run (its
            # letters are listed every run for roundup_days), and the run carries a note.
            errors = getattr(ctx, "list_errors", None)
            if errors is not None:
                errors.append(f"{path_of(item.url)}: {type(exc).__name__}: {exc}"[:300])
    return items + letters


def read_roundup(ctx: FetchContext, item: Item, source: SourceConfig) -> list[Item]:
    api = f"{CONTENT_API}{path_of(item.url)}"
    page = ctx.get(api, accept="application/json", raise_for_status=False)
    ctx.forget(api)                     # fetch_detail of a new roundup reads it again in full
    if page.status != 200:
        raise ParseError(f"GOV.UK content API answered HTTP {page.status} for {item.url}")
    try:
        data = page.json()
    except ValueError as exc:
        raise ParseError(f"GOV.UK content API returned non-JSON for {item.url}") from exc
    return roundup_letters(data, item, source)


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
