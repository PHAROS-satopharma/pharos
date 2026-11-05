"""Probe a URL an admin wants to add as a source (``python -m collectors.run --probe-id <uuid>``).

Reads the ``probe_result`` row, fetches the URL, detects the channel (an RSS/Atom feed by
content type or XML root, JSON by content type, otherwise HTML), runs the matching parser
(``feed`` or ``generic_html``) WITHOUT writing documents, and writes up to 20 items, the channel and
parser detected and the status back to ``probe_result``. Nothing is archived for a probe.
"""

from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any

from collectors.core.context import (PRIVATE_NETWORK_MESSAGE, FetchContext, SourceBlocked,
                                     UnsafeAddress)
from collectors.core.models import Fetched, SourceConfig
from collectors.core.registry import load_parser

log = logging.getLogger(__name__)

MAX_ITEMS = 20
_XML_ROOT = re.compile(rb"^\s*(?:<\?xml[^>]*>\s*)?(?:<!--.*?-->\s*)*<(rss|feed|rdf:RDF)\b", re.S | re.I)


def detect(fetched: Fetched) -> tuple[str, str | None]:
    """-> (channel, parser) for a fetched URL."""
    ctype = fetched.mime
    m = _XML_ROOT.match(fetched.content[:4096])
    if m:
        return ("atom" if m.group(1).lower() == "feed" else "rss"), "feed"
    if "rss" in ctype:
        return "rss", "feed"
    if "atom" in ctype:
        return "atom", "feed"
    if "json" in ctype:
        return "json", None
    if fetched.is_pdf:
        return "html", None
    return "html", "generic_html"


def serialise(items: list) -> list[dict]:
    return [{"title": i.title, "url": i.url, "published": i.published.isoformat() if i.published else None,
             "doc_type": i.doc_type, "lang": i.lang, "external_id": i.external_id,
             "attachments": i.attachment_urls[:5]} for i in items[:MAX_ITEMS]]


def run_probe(store: Any, ctx: FetchContext, probe_id: str) -> dict:
    row = store.get_probe(probe_id)
    if not row:
        raise SystemExit(f"probe_result {probe_id} not found")
    url = row["url"]
    store.update_probe(probe_id, status="running")
    result: dict[str, Any] = {"status": "failed"}
    try:
        fetched = ctx.get(url)
        channel, parser = detect(fetched)
        # The parser reads the URL again; a site that honours ETags would answer that with an empty 304.
        ctx.forget(url)
        result.update(channel_detected=channel, parser_detected=parser)
        if parser is None:
            result.update(status="ok", items=[], error="No parser for this content type yet; "
                                                       "the source needs a dedicated parser.")
        else:
            module = load_parser(parser)
            source = SourceConfig(id="probe", regulator_id="PROBE", kind="safety", channel=channel,
                                  url=url, parser=parser, languages=[], schedule="4h", enabled=True,
                                  options={}, expected_max_gap_days=None)
            items = module.list_items(ctx, source)
            result.update(status="ok", items=serialise(items), error=None if items else
                          "The page loaded but no items were recognised.")
    except UnsafeAddress:
        result.update(status="failed", error=PRIVATE_NETWORK_MESSAGE)
    except SourceBlocked as exc:
        result.update(status="failed", error=f"Blocked by a bot check: {exc}")
    except Exception as exc:  # noqa: BLE001 - every failure is reported to the admin screen
        log.warning("probe %s failed: %s", probe_id, traceback.format_exc())
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:1000])
    result["finished_at"] = datetime.now(timezone.utc)
    store.update_probe(probe_id, **result)
    return result
