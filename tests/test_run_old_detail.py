"""Health Canada's open-data file lists every recall ever, and each notice page takes about two seconds.
An old notice never alerts, so with ``old_detail: matched_only`` its page is opened only when its own row
already names a watched term; a recent one always gets its page. Nothing leaves the machine."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.run import MAX_NEW_ITEMS, Runner

FIX = Path(__file__).resolve().parent / "fixtures"
TEMPLATE = json.loads((FIX / "hc-recalls/HCRSAMOpenData-slice.json").read_text(encoding="utf-8"))[0]
_, SOURCES, _ = load_catalogue()
SRC = {s.id: s for s in SOURCES}["hc-recalls"]
PAGE = "https://recalls-rappels.canada.ca/en/alert-recall/"


def row(nid: str, updated: str, product: str) -> dict:
    return {**TEMPLATE, "NID": nid, "Last updated": updated, "Product": product, "Title": f"{product} recall",
            "Issue": "Product quality", "What you should do": "Return it.", "URL": PAGE + nid,
            "Organization": "Drugs and health products", "Category": "Drugs"}


ROWS = [row("1", "2019-05-01", "Sertraline 50 mg capsules"),          # old, not ours: no page
        row("2", "2019-05-02", "Lornoxicam 8 mg tablets"),            # old, names lornoxicam: page
        row("3", date.today().isoformat(), "Sertraline 25 mg capsules")]  # recent: always its page


class Server:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == SRC.url:
            return httpx.Response(200, content=json.dumps(ROWS).encode(),
                                  headers={"content-type": "application/json"})
        assert url.startswith(PAGE), url
        self.pages.append(url.rsplit("/", 1)[-1])
        return httpx.Response(200, content=b"<html><main><p>Recall notice.</p></main></html>",
                              headers={"content-type": "text/html; charset=utf-8"})


class NoTelegram:
    def send_message(self, *a, **k):
        return {"ok": True, "result": {"message_id": 1}}

    send_document = send_message


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "PHAROS_IMAP_HOST", "PHAROS_IMAP_USER", "PHAROS_IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


def run_once(tmp_path, src) -> tuple[Server, MemoryStore]:
    server, store = Server(), MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    ctx = FetchContext(None, store.create_run("manual", "test-sha"), archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(server), host_gap_s=0)
    settings = store.settings()
    runner = Runner(store, ctx, Notifier(store, settings, telegram=NoTelegram()), settings)
    stats = runner.run_source(src)
    ctx.close()
    assert not stats.failed and stats.new == 3
    return server, store


def test_an_old_notice_opens_its_page_only_when_its_row_names_a_watched_term(tmp_path):
    server, store = run_once(tmp_path, SRC)
    assert sorted(server.pages) == ["2", "3"]
    assert len([d for d in store.document.values() if d["source_id"] == "hc-recalls"]) == 3  # all stored


def test_without_the_option_every_new_notice_opens_its_page(tmp_path):
    import dataclasses

    plain = dataclasses.replace(SRC, options={k: v for k, v in SRC.options.items() if k != "old_detail"})
    server, _ = run_once(tmp_path, plain)
    assert sorted(server.pages) == ["1", "2", "3"]


def test_health_canada_may_take_more_than_the_default_new_items_per_run():
    assert SRC.options["old_detail"] == "matched_only"
    assert SRC.options["max_new_items"] > MAX_NEW_ITEMS


def test_max_new_items_caps_a_run_and_the_rest_wait(tmp_path):
    import dataclasses


    capped = dataclasses.replace(SRC, options={**SRC.options, "max_new_items": 2})
    server, store = Server(), MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    ctx = FetchContext(None, store.create_run("manual", "test-sha"), archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(server), host_gap_s=0)
    settings = store.settings()
    stats = Runner(store, ctx, Notifier(store, settings, telegram=NoTelegram()), settings).run_source(capped)
    ctx.close()
    assert stats.new == 2
