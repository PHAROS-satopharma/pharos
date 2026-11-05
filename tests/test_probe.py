"""Probing a link an admin wants to add: the page it reads to detect the channel is the page the parser
reads. All traffic goes through httpx.MockTransport; nothing leaves the machine, nothing sleeps."""

from __future__ import annotations

from pathlib import Path

import httpx

from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.probe import run_probe

FEED = (Path(__file__).parent / "fixtures" / "mhra-dsu" / "feed.atom").read_bytes()
URL = "https://www.gov.uk/drug-safety-update.atom"


def test_probe_of_a_feed_that_answers_304_on_a_repeat_still_finds_its_notices(tmp_path):
    # gov.uk sends an ETag and answers the second, conditional request with 304 and no body
    def handler(req: httpx.Request) -> httpx.Response:
        if req.headers.get("if-none-match") == '"dsu-1"':
            return httpx.Response(304, headers={"etag": '"dsu-1"'})
        return httpx.Response(200, headers={"content-type": "application/atom+xml; charset=utf-8",
                                            "etag": '"dsu-1"'}, content=FEED)

    store = MemoryStore()
    store.update_probe("p1", url=URL, status="queued")
    ctx = FetchContext(None, "probe", archive=Archive(enabled=False), dry_run=True,
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    ctx._sleep = lambda s: None
    try:
        result = run_probe(store, ctx, "p1")
    finally:
        ctx.close()
    assert result["status"] == "ok" and result["parser_detected"] == "feed"
    assert result["items"], result.get("error")
    assert result["error"] is None
