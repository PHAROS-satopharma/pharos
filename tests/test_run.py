"""The runner end to end on an in-memory store: real EMA PSUSA rows served through httpx.MockTransport,
the production seed watchlist, a local archive in tmp_path, and a Telegram stub that fails the test
if it is called. Nothing leaves the machine."""

from __future__ import annotations

import copy
import dataclasses
import json
import time
from datetime import date
from pathlib import Path

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.run import DOWN_AFTER, Runner, parse_args, select_sources

FIX = Path(__file__).resolve().parent / "fixtures"
PSUSA = json.loads((FIX / "ema-psusa/psusa-slice.json").read_text(encoding="utf-8"))
_, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}
# Detail pages are not part of this test: the rows themselves are matched.
SRC = dataclasses.replace(CFG["ema-psusa"], options={**CFG["ema-psusa"].options, "detail": "never"})


class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called")

    send_document = send_message


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "PHAROS_IMAP_HOST", "PHAROS_IMAP_USER", "PHAROS_IMAP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


class Server:
    """Answers the PSUSA URL with whatever ``self.reply`` holds."""

    def __init__(self) -> None:
        self.reply: tuple[int, bytes, str] = (200, json.dumps(PSUSA).encode(), "application/json")
        self.hits = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url).split("?")[0] == SRC.url, request.url
        self.hits += 1
        status, body, ctype = self.reply
        return httpx.Response(status, content=body, headers={"content-type": ctype})


def setup(tmp_path, server: Server):
    store = MemoryStore()
    ing_id, _ = store.load_seed()
    sync_catalogue(store)
    store.person["p1"] = {"id": "p1", "full_name": "Reviewer One", "telegram_chat_id": 111,
                          "role": "reviewer", "active": True}
    store.person["p2"] = {"id": "p2", "full_name": "Admin Two", "telegram_chat_id": 222,
                          "role": "admin", "active": True}
    store.subscription += [{"person_id": "p1", "kind": "ingredient", "ingredient_id": ing_id},
                           {"person_id": "p2", "kind": "admin_health", "ingredient_id": None}]
    run_id = store.create_run("manual", "test-sha")
    ctx = FetchContext(None, run_id, archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(server), host_gap_s=0)
    settings = store.settings()
    notifier = Notifier(store, settings, telegram=ExplodingTelegram())
    return store, ctx, Runner(store, ctx, notifier, settings), ing_id


def last_source_run(store: MemoryStore) -> dict:
    return list(store.source_run.values())[-1]


def test_first_run_seeds_without_alerts(tmp_path):
    server = Server()
    store, ctx, runner, ing_id = setup(tmp_path, server)
    stats = runner.run_source(SRC)
    assert not stats.failed and stats.error is None
    assert (stats.seen, stats.new, stats.matched) == (9, 9, 1)
    sr = last_source_run(store)
    assert (sr["items_seen"], sr["items_new"], sr["items_matched"], sr["http_status"]) == (9, 9, 1, 200)
    docs = [d for d in store.document.values() if d["source_id"] == "ema-psusa"]
    assert len(docs) == 9 and all(d["is_backfill"] for d in docs)   # the first run is the seed
    assert all(d["sha256"] and d["r2_key"].startswith("sha256/") for d in docs)
    lorno = next(d for d in docs if d["external_id"] == "PSUSA/00001911/202412")
    matches = [m for m in store.match if m["document_id"] == lorno["id"]]
    assert matches and all(m["ingredient_id"] == ing_id for m in matches)
    assert {m["field"] for m in matches} >= {"structured"}
    # document_text is kept for matched documents only
    assert {t["document_id"] for t in store.document_text} <= {lorno["id"]}
    assert len(store.issue) == 1 and store.notification == []       # seed → no alert
    assert store.source["ema-psusa"]["health"] in ("ok", "degraded")
    ctx.close()


def test_second_run_alerts_only_new_lornoxicam(tmp_path):
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    runner.run_source(SRC)
    fresh = copy.deepcopy(PSUSA)
    row = copy.deepcopy(next(r for r in PSUSA["data"] if r["procedure_number"] == "PSUSA/00001911/202412"))
    row["procedure_number"] = "PSUSA/00001911/202612"
    row["first_published_date"] = date.today().strftime("%d/%m/%Y")
    row["psusa_url"] = "https://www.ema.europa.eu/en/medicines/psusa/psusa-00001911-202612"
    fresh["data"].insert(0, row)
    server.reply = (200, json.dumps(fresh).encode(), "application/json")
    stats = runner.run_source(SRC)
    assert (stats.seen, stats.new, stats.matched) == (10, 1, 1)
    assert len(stats.alerts) == 1
    rows = [n for n in store.notification if n["kind"] == "immediate"]
    assert len(rows) == 1 and rows[0]["person_id"] == "p1" and rows[0]["dry_run"] is True
    assert "PSUSA/00001911/202612" in rows[0]["summary"]
    # the run after that sees nothing new
    stats = runner.run_source(SRC)
    assert stats.new == 0 and len([n for n in store.notification if n["kind"] == "immediate"]) == 1
    ctx.close()


def test_shape_change_is_degraded(tmp_path):
    server = Server()
    server.reply = (200, b'{"rows": []}', "application/json")
    store, ctx, runner, _ = setup(tmp_path, server)
    stats = runner.run_source(SRC)
    assert stats.failed and stats.error.startswith("parse:")
    assert store.source["ema-psusa"]["health"] == "degraded"
    health = [n for n in store.notification if n["kind"] == "health"]
    assert len(health) == 1 and health[0]["person_id"] == "p2" and health[0]["dry_run"]
    assert last_source_run(store)["error"].startswith("parse:")       # the screening log row
    ctx.close()


def test_three_failures_mark_down_and_alert_once(tmp_path):
    server = Server()
    server.reply = (503, b"Service Unavailable", "text/plain")
    store, ctx, runner, _ = setup(tmp_path, server)
    for _ in range(DOWN_AFTER + 1):
        stats = runner.run_source(SRC)
        assert stats.failed
    assert store.source["ema-psusa"]["health"] == "down"
    assert store.source["ema-psusa"]["consecutive_failures"] == DOWN_AFTER + 1
    assert len([n for n in store.notification if n["kind"] == "health"]) == 1
    assert all(sr["error"] for sr in store.source_run.values())
    ctx.close()


def test_bot_check_is_blocked_not_bypassed(tmp_path):
    server = Server()
    server.reply = (403, b"<html><head><title>Just a moment...</title></head><body></body></html>",
                    "text/html")
    store, ctx, runner, _ = setup(tmp_path, server)
    stats = runner.run_source(SRC)
    assert stats.error.startswith("blocked:") and not stats.failed
    assert store.source["ema-psusa"]["health"] == "blocked"
    assert server.hits == 1                                           # no retry, no workaround
    ctx.close()


def test_select_sources_and_args():
    assert all(s.schedule == "4h" and s.kind != "spc" for s in select_sources(SOURCES, "4h", None, False))
    assert [s.id for s in select_sources(SOURCES, "4h", "ema-psusa", False)] == ["ema-psusa"]
    with pytest.raises(SystemExit):
        select_sources(SOURCES, "4h", "no-such-source", False)
    assert parse_args(["--backfill"]).backfill == 0
    assert parse_args(["--backfill", "12"]).backfill == 12
    assert parse_args([]).backfill is None
    assert parse_args(["--schedule", "daily", "--dry-run"]).dry_run


def test_an_old_notice_found_by_a_regular_run_is_history(tmp_path):
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    runner.run_source(SRC)
    old = copy.deepcopy(PSUSA)
    row = copy.deepcopy(next(r for r in PSUSA["data"] if r["procedure_number"] == "PSUSA/00001911/202412"))
    row["procedure_number"] = "PSUSA/00001911/201506"
    row["first_published_date"] = "15/06/2015"
    row["psusa_url"] = "https://www.ema.europa.eu/en/medicines/psusa/psusa-00001911-201506"
    old["data"].insert(0, row)
    server.reply = (200, json.dumps(old).encode(), "application/json")
    stats = runner.run_source(SRC)
    assert (stats.new, stats.matched) == (1, 1) and stats.alerts == []
    doc = next(d for d in store.document.values() if d["external_id"] == "PSUSA/00001911/201506")
    assert doc["is_backfill"]
    assert all(i["is_backfill"] for i in store.issue.values())
    ctx.close()


def test_a_run_past_its_time_budget_starts_no_more_sources(tmp_path):
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    runner.deadline = time.monotonic() - 1           # the budget is already used up
    assert runner.run([SRC])                         # stopping on time is not a failure
    assert server.hits == 0 and store.source_run == {}
    runner.deadline = time.monotonic() + 3600
    assert runner.run([SRC]) and server.hits == 1
    ctx.close()


def test_each_run_records_the_slot_it_served(tmp_path):
    store = MemoryStore()
    rid = store.create_run("cron", "sha", "12h")
    assert store.run[rid]["schedule"] == "12h"
