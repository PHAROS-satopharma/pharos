"""PHAROS — Läkemedelsverket / MPA (Sweden) news and safety news (säkerhetsnyheter, DHPC).

Source: ``mpa-news``. The news list on lakemedelsverket.se is drawn by script from the site's own
JSON API, which this parser reads directly (no browser needed). It answers only with the header
``Accept-Language: sv``:

``https://www.lakemedelsverket.se/api/newslist?query=&pageTypeId=&take=20&skip=0&from=&to=&sortId=1&skipHighlight=false&categoryIds=225``

* ``pageTypeId`` empty = news and safety news together (as verified); 2 = Säkerhetsnyheter only,
  1 = Nyheter; 0 answers HTTP 500, so it is never sent;
* ``categoryIds`` (checked 4 Nov 2026): 225 DHPC, 221 Effekt och säkerhet, 222 Indragning,
  224 Kvalitetsdefekt, 223 Bristsituation;
* ``sortId`` 1 = Datum (fallande).

Each item: ``heading`` (the title as published), ``preamble`` (HTML), ``url`` (``/sv/nyheter/<slug>``),
``startPublish`` (ISO), ``categories`` (labels) and ``contentId``. Detail text comes from the
Optimizely content API ``/api/episerver/v3.0/content/<contentId>?expand=*``: ``mainBody.value`` is a
list of fragments ``{html, content}``; the HTML fragments are the letter, and PDFs are linked as
``/globalassets/dokument/…pdf``.

doc_type from the categories: DHPC → ``dhpc``; Indragning → ``recall``; Kvalitetsdefekt →
``recall``; Effekt och säkerhet → ``safety_update``; otherwise ``safety_alert``.

Options:

* ``category_ids`` — list of ids (default ``[225, 221, 222, 224]``), read one request per id;
* ``all_safety_news`` — also read every safety news item (``pageTypeId=2``, no ``categoryIds``:
  an empty ``categoryIds`` answers HTTP 400). Some safety news carry only the label
  "Säkerhetsnyhet" and no category, so no category request returns them (2026-04-13 "Nya krav på
  kontroll av leverprover vid behandling med Ontozry", checked 5 Nov 2026). Items labelled
  ``exclude_categories`` (default "Läkemedel för djur", "Medicinteknik") are left out of this pass;
* ``page_type_id`` (empty), ``take`` (20; a backfill reads ``backfill_pages`` × ``take``);
* ``include_keywords`` / ``exclude_keywords``; ``lang`` (``sv``).

If the API ever disappears, the page is client-rendered: ``ParseError`` is raised (the API answered
but changed) rather than an empty list.
"""

from __future__ import annotations

import html as htmllib
import json
from datetime import date, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from collectors.parsers._html_util import (absolute, block_text, clean, keep, links_in, local_date,
                                           pages_to_read)
from collectors.parsers.base import Item, ParseError, SourceConfig, soup

HOST = "https://www.lakemedelsverket.se"
API = HOST + "/api/newslist"
CONTENT_API = HOST + "/api/episerver/v3.0/content/{id}?expand=*"
HEADERS = {"Accept-Language": "sv"}
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def published_date(stamp: str | None, lang: str | None) -> date | None:
    """The day it was published in Sweden. startPublish is UTC: 23:30 on the 4th there is the 5th in Stockholm."""
    try:
        moment = datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return local_date((stamp or "")[:10], lang)
    if moment.tzinfo is None:
        return moment.date()
    return moment.astimezone(STOCKHOLM).date()
DEFAULT_CATEGORIES = [225, 221, 222, 224]
DEFAULT_EXCLUDED = ["Läkemedel för djur", "Medicinteknik"]


def doc_type_for(categories: list[str]) -> str:
    cats = {c.casefold() for c in categories or []}
    if "dhpc" in cats:
        return "dhpc"
    if "indragning" in cats or "kvalitetsdefekt" in cats:
        return "recall"
    if "effekt och säkerhet" in cats:
        return "safety_update"
    if "bristsituation" in cats or "avregistrering" in cats:
        return "other"
    return "safety_alert"


def api_url(category_id: int | None, *, page_type: int | str = "", take: int = 20,
            skip: int = 0) -> str:
    q = {"query": "", "pageTypeId": page_type, "take": take, "skip": skip, "from": "", "to": "",
         "sortId": 1, "skipHighlight": "false"}
    if category_id is not None:
        q["categoryIds"] = category_id
    return f"{API}?{urlencode(q)}"


def parse_newslist(data: dict, source: SourceConfig) -> list[Item]:
    if not isinstance(data, dict) or "items" not in data:
        raise ParseError("Läkemedelsverket newslist answer has no 'items'")
    lang = source.lang or "sv"
    out: list[Item] = []
    for row in data["items"] or []:
        title = clean(htmllib.unescape(row.get("heading") or ""))
        path = row.get("url") or ""
        if not title or not path:
            continue
        preamble = block_text(soup(row.get("preamble") or "<p></p>"))
        if not keep(source, title, preamble):
            continue
        cats = list(row.get("categories") or [])
        cid = row.get("contentId")
        out.append(Item(
            external_id=f"mpa:{cid}" if cid else path, url=absolute(path, HOST), title=title,
            published=published_date(row.get("startPublish"), lang),
            doc_type=doc_type_for(cats), lang=lang, body_text=preamble or None,
            structured={"content_id": cid, "categories": cats,
                        "content_type": row.get("contentType")}))
    return out


def list_items(ctx, source: SourceConfig) -> list[Item]:
    opts = source.options or {}
    cats = opts.get("category_ids") or DEFAULT_CATEGORIES
    take = int(opts.get("take", 20))
    page_type = opts.get("page_type_id", "")
    if page_type in (0, "0"):
        page_type = ""
    queries: list[tuple[int | None, int | str]] = [(cid, page_type) for cid in cats]
    if opts.get("all_safety_news"):
        queries.append((None, 2))
    excluded = {c.casefold() for c in opts.get("exclude_categories", DEFAULT_EXCLUDED)}
    out: list[Item] = []
    seen: set[str] = set()
    for cid, ptype in queries:
        for page in range(pages_to_read(ctx, source)):
            f = ctx.get(api_url(cid, page_type=ptype, take=take, skip=page * take),
                        accept="application/json", headers=HEADERS)
            if f.status == 304:
                break
            try:
                data = f.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise ParseError(f"Läkemedelsverket API did not answer JSON: {exc}") from exc
            batch = parse_newslist(data, source)
            if cid is None:
                batch = [it for it in batch
                         if not {c.casefold() for c in it.structured["categories"]} & excluded]
            for it in batch:
                if it.external_id not in seen:
                    seen.add(it.external_id)
                    out.append(it)
            if len(data.get("items") or []) < take:
                break
    return out


def _fragments(body) -> list[str]:
    """HTML fragments of an Optimizely XhtmlString value (strings or {html, content} dicts)."""
    if body is None:
        return []
    value = body.get("value") if isinstance(body, dict) else body
    if isinstance(value, str):
        return [value]
    out: list[str] = []
    for frag in value or []:
        if isinstance(frag, str):
            out.append(frag)
        elif isinstance(frag, dict):
            if frag.get("html"):
                out.append(frag["html"])
            inner = frag.get("content")
            if isinstance(inner, dict) and inner.get("mainBody"):
                out.extend(_fragments(inner["mainBody"]))
    return out


def parse_content(data: dict) -> tuple[str, list[str]]:
    """-> (body text, PDF links) from the content API answer."""
    html = "\n".join(_fragments(data.get("mainBody")))
    doc = soup(f"<div>{html}</div>")
    text = block_text(doc)
    return text, links_in([doc], HOST, patterns=(".pdf",))


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    cid = (item.structured or {}).get("content_id")
    if not cid:
        return item
    f = ctx.get(CONTENT_API.format(id=cid), accept="application/json", headers=HEADERS)
    if f.status != 200:
        return item
    try:
        data = f.json()
    except ValueError:
        return item
    text, pdfs = parse_content(data)
    if text:
        item.body_text = text
    for u in pdfs:
        if u not in item.attachment_urls:
            item.attachment_urls.append(u)
    return item
