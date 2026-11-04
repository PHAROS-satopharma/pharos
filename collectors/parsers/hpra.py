"""PHAROS — HPRA (Ireland) safety notices.

Source: ``hpra-notices``. The public safety-notice list is filled from the site's own JSON API
(OData), which this parser reads directly:

``https://www.hpra.ie/api/safety-notices/safetynotices?$select=id,title,date,urlname,safetynotices&$top=50&$count=true&$orderby=date desc``

Each row: ``Id``, ``Title``, ``Date`` (ISO), ``UrlName`` and ``safetynotices`` (a list of taxon ids of
taxonomy ``7cd8b045-364e-499f-9f10-2e247c1dc64c``). Only children of "Medicines for human use"
(``abc52ebb-…``) are kept, mapped in ``TAXA`` below (checked 4 Nov 2026). Devices, veterinary and
cosmetics notices carry other taxa and are skipped.

Detail page: ``https://www.hpra.ie/safety-information/safety-notices/article/<UrlName>``; body
``article.standard-content``; originals on ``assets.hpra.ie/…pdf?sfvrsn=…``.

Options:

* ``api_url`` — overrides the API URL above (``source.url`` may be the human page).
* ``top`` — rows per request (50); a backfill reads up to ``backfill_pages`` × ``top`` with ``$skip``.
* ``include_taxa`` — taxon ids to keep (default: every key of ``TAXA``).
* ``include_keywords`` / ``exclude_keywords``; ``lang`` (``en``).
"""

from __future__ import annotations

from urllib.parse import quote

from collectors.parsers._html_util import fill_detail, keep, local_date, pages_to_read
from collectors.parsers.base import Item, ParseError, SourceConfig

API = ("https://www.hpra.ie/api/safety-notices/safetynotices"
       "?$select=id,title,date,urlname,safetynotices&$count=true&$orderby=date%20desc")
DETAIL = "https://www.hpra.ie/safety-information/safety-notices/article/"

# Children of "Medicines for human use" → doc_type.
TAXA = {
    "0087a072-d34f-4a22-a0b0-d26cd2daead3": ("DHPC", "dhpc"),
    "9e89a9e7-7508-4dcd-91c1-bea3c290e43e": ("Safety update", "safety_update"),
    "945f98ba-5a64-4a53-98c7-ee7f6affecff": ("Recall", "recall"),
    "9a4182a4-df59-49c5-bc2c-23133b899bfc": ("PRAC", "safety_update"),
    "12eaabdc-7722-4898-ac22-8079ba4c20b3": ("Product information update", "safety_update"),
    "ca557df7-d978-4867-919d-ffd264538d35": ("Caution-in-use notification", "safety_alert"),
}


def parse_rows(data: dict, source: SourceConfig) -> list[Item]:
    if not isinstance(data, dict) or "value" not in data:
        raise ParseError("HPRA API answer has no 'value' list")
    wanted = set((source.options or {}).get("include_taxa") or TAXA)
    lang = source.lang or "en"
    items: list[Item] = []
    for row in data["value"]:
        taxa = [t for t in (row.get("safetynotices") or []) if t in wanted]
        if not taxa:
            continue
        title = (row.get("Title") or "").strip()
        slug = row.get("UrlName") or ""
        if not title or not slug or not keep(source, title):
            continue
        url = DETAIL + quote(slug, safe="()-_.~!*'")
        items.append(Item(
            external_id=row.get("Id") or slug, url=url, title=title,
            published=local_date((row.get("Date") or "")[:10], lang),
            doc_type=TAXA.get(taxa[0], ("", "safety_update"))[1], lang=lang,
            structured={"hpra_id": row.get("Id"), "taxa": [TAXA.get(t, (t,))[0] for t in taxa],
                        "url_name": slug}))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    opts = source.options or {}
    api = opts.get("api_url") or (source.url if "/api/" in source.url else API)
    top = int(opts.get("top", 50))
    out: list[Item] = []
    for page in range(pages_to_read(ctx, source)):
        sep = "&" if "?" in api else "?"
        url = f"{api}{sep}$top={top}" + (f"&$skip={page * top}" if page else "")
        f = ctx.get(url, accept="application/json")
        if f.status == 304:
            break
        try:
            data = f.json()
        except ValueError as exc:
            raise ParseError(f"HPRA API did not answer JSON: {exc}") from exc
        out.extend(parse_rows(data, source))
        if len(data.get("value") or []) < top:
            break
    return out


def fetch_detail(ctx, source: SourceConfig, item: Item) -> Item:
    return fill_detail(item, ctx.get(item.url), "article.standard-content",
                       patterns=(".pdf",))
