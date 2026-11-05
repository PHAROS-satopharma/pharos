"""PHAROS — e-mail newsletters as a source (Fimea, TGA, FDA MedWatch, famhp VIG-news): reads ``inbound_email``.

Sources: ``fimea-email``, ``tga-email``, ``fda-email`` and ``famhp-email``. Fimea's web site sits behind a Cloudflare check that
PHAROS never tries to pass, and TGA drops non-browser clients, so both regulators' e-mail
newsletters are subscribed to by the PHAROS mailbox. ``collectors.core.imap_inbox`` (A1) stores each
message whose From domain is on the source's ``options.from_domains`` in ``inbound_email``
(``source_id``, ``received_at``, ``from_addr``, ``subject``, ``r2_key`` of the raw message,
``text_body``, ``html_body``, ``processed_at``). This parser turns those rows into items.

One item per message by default: title = the subject exactly as sent (Finnish/Swedish for Fimea),
``body_text`` = the plain text (or the HTML converted to text), the published date = the date it
was received. With ``split_links`` set, every link in the HTML body whose href matches that regex
becomes its own item instead (title = link text, the message subject kept in ``structured``) — for
digests that list several notices.

``Item.url`` is the first link to ``web_domain`` in the message (the notice on the regulator's
site), else ``options.web_url``, else ``email:<row id>``. Links into a blocked site are kept as
URLs only — never fetched (``fetch_attachments`` false).

Rows are read when unprocessed, or received within ``reread_days`` (14) — the runner's
``(source_id, external_id)`` dedupe makes a re-read harmless; ``processed_at`` is then set.

Options: ``from_domains`` (read by imap_inbox), ``web_domain`` (``fimea.fi`` / ``tga.gov.au``),
``web_url``, ``split_links``, ``doc_type`` (``newsletter``), ``fetch_attachments`` (false),
``reread_days`` (14), ``include_keywords`` / ``exclude_keywords``; ``lang`` (source language).
"""

from __future__ import annotations

import re
from datetime import date, datetime

from collectors.parsers._html_util import absolute, block_text, clean, keep, node_text
from collectors.parsers.base import Item, SourceConfig, soup

SQL = """select id, received_at, from_addr, subject, r2_key, text_body, html_body, processed_at
           from inbound_email
          where source_id = %(sid)s
            and (processed_at is null or received_at > now() - make_interval(days => %(days)s))
          order by received_at desc
          limit 500"""
MARK = "update inbound_email set processed_at = now() where id = any(%(ids)s::uuid[]) and processed_at is null"


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _body(row: dict) -> str:
    text = (row.get("text_body") or "").strip()
    if text:
        return "\n".join(clean(ln) for ln in text.splitlines() if clean(ln))
    if row.get("html_body"):
        return block_text(soup(row["html_body"]))
    return ""


def _links(row: dict) -> list[tuple[str, str]]:
    if not row.get("html_body"):
        return [(u, "") for u in re.findall(r"https?://[^\s<>\")']+", row.get("text_body") or "")]
    doc = soup(row["html_body"])
    out = []
    for a in doc.select("a[href]"):
        href = a["href"].strip()
        if href.startswith(("http://", "https://")):
            out.append((absolute(href, href), node_text(a)))
    return out


def items_from_rows(rows: list[dict], source: SourceConfig) -> list[Item]:
    opts = source.options or {}
    lang = source.lang
    domain = (opts.get("web_domain") or "").lower()
    split = re.compile(opts["split_links"]) if opts.get("split_links") else None
    doc_type = opts.get("doc_type", "newsletter")
    fetch_att = bool(opts.get("fetch_attachments", False))
    items: list[Item] = []
    for row in rows:
        rid = str(row["id"])
        subject = clean(row.get("subject")) or "(no subject)"
        received = _day(row.get("received_at"))
        body = _body(row)
        links = _links(row)
        meta = {"inbound_email_id": rid, "from": row.get("from_addr"), "subject": subject,
                "raw_r2_key": row.get("r2_key")}
        if split is not None:
            seen: set[str] = set()
            for url, text in links:
                if not split.search(url) or url in seen or not text:
                    continue
                seen.add(url)
                if not keep(source, text, subject):
                    continue
                items.append(Item(external_id=url, url=url, title=text, published=received,
                                  doc_type=doc_type, lang=lang, body_text=text,
                                  attachment_urls=[url] if fetch_att else [],
                                  structured=meta))
            if seen:
                continue
        if not keep(source, subject, body):
            continue
        web = next((u for u, _ in links if domain and domain in u.lower()), None)
        url = web or opts.get("web_url") or f"email:{rid}"
        pdfs = [u for u, _ in links if u.lower().split("?")[0].endswith(".pdf")] if fetch_att \
            else []
        items.append(Item(external_id=f"email:{rid}", url=url, title=subject, published=received,
                          doc_type=doc_type, lang=lang, body_text=body or None,
                          attachment_urls=pdfs, structured=meta))
    return items


def list_items(ctx, source: SourceConfig) -> list[Item]:
    if ctx.db is None:
        return []
    days = int((source.options or {}).get("reread_days", 14))
    rows = ctx.db.fetchall(SQL, {"sid": source.id, "days": days})
    items = items_from_rows(rows, source)
    fresh = [str(r["id"]) for r in rows if r.get("processed_at") is None]
    if fresh and not getattr(ctx, "dry_run", False):
        ctx.db.execute(MARK, {"ids": fresh})
    return items
