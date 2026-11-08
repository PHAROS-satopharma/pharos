"""The runner end to end on an in-memory store: real EMA PSUSA rows served through httpx.MockTransport,
the production seed watchlist, a local archive in tmp_path, and a Telegram stub that fails the test
if it is called. Nothing leaves the machine."""

from __future__ import annotations

import copy
import dataclasses
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import RETRY_WAITS_S, FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.run import DOWN_AFTER, Runner, latest_published, parse_args, select_sources

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
    slept: list[float] = []
    ctx._sleep = slept.append            # the 30 s + 60 s slow-down waits, recorded, not slept
    for _ in range(DOWN_AFTER + 1):
        stats = runner.run_source(SRC)
        assert stats.failed
    assert server.hits == (DOWN_AFTER + 1) * 3                       # first try + two retries
    assert [w for w in slept if w in RETRY_WAITS_S] == list(RETRY_WAITS_S) * (DOWN_AFTER + 1)
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
    literature = select_sources(SOURCES, "literature", None, False)
    assert [s.id for s in literature] == ["pubmed", "europepmc"] and all(s.schedule == "daily" for s in literature)
    off = [dataclasses.replace(s, enabled=False) if s.id == "pubmed" else s for s in SOURCES]
    assert [s.id for s in select_sources(off, "literature", None, False)] == ["europepmc"]
    off = [dataclasses.replace(s, enabled=False) if s.kind == "literature" else s for s in SOURCES]
    assert select_sources(off, "literature", None, False) == []
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


def test_one_bad_notice_never_blocks_the_rest(tmp_path, monkeypatch):
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    real = runner.process_item

    def flaky(src, module, item, **kw):
        if item.external_id == "PSUSA/00001911/202412":
            raise ValueError("A string literal cannot contain NUL (0x00) characters.")
        return real(src, module, item, **kw)

    monkeypatch.setattr(runner, "process_item", flaky)
    stats = runner.run_source(SRC)
    assert not stats.failed and stats.new == 8                       # the other eight are stored
    assert "1 item(s) failed" in stats.error and "ValueError" in stats.error
    assert store.source["ema-psusa"]["consecutive_failures"] == 0
    ctx.close()



def test_a_part_of_the_list_not_read_is_a_note_not_a_failure(tmp_path, monkeypatch):
    # A parser that reads extra pages for its list (MHRA's monthly roundups) notes the one it could not read
    # in ctx.list_errors and returns the rest; the run stores the rest and completes with a note.
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    real = runner.load_parser

    def load(name):
        module = real(name)

        class Wrapped:
            def __getattr__(self, attr):
                return getattr(module, attr)

            @staticmethod
            def list_items(c, src):
                items = module.list_items(c, src)
                c.list_errors.append("/drug-device-alerts/mhra-safety-roundup-october-2026: "
                                     "ParseError: GOV.UK content API returned non-JSON")
                return items

        return Wrapped()

    monkeypatch.setattr(runner, "load_parser", load)
    stats = runner.run_source(SRC)
    assert not stats.failed and stats.new == 9
    assert stats.error.startswith("1 item(s) failed; first: /drug-device-alerts/mhra-safety-roundup")
    assert store.source["ema-psusa"]["consecutive_failures"] == 0
    assert last_source_run(store)["error"] == stats.error
    ctx.close()

def test_time_budget_cuts_a_source_cleanly_and_seeding_continues(tmp_path):
    from collectors.run import SOURCE_BUDGET_S

    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    ticks = iter(range(0, 10_000, SOURCE_BUDGET_S // 2 + 1))         # every look at the clock: +5 min
    runner.clock = lambda: next(ticks)
    stats = runner.run_source(SRC)
    assert not stats.failed and stats.new == 1                       # one notice, then the budget
    assert "time budget reached: 8 new item(s) wait" in stats.error
    assert store.source["ema-psusa"].get("last_ok_at") is None       # not a complete run
    # the next run carries on: still the seed, so the old notices behind the cut never alert
    runner.clock = lambda: 0
    stats = runner.run_source(SRC)
    assert stats.new == 8 and stats.alerts == [] and store.notification == []
    docs = [d for d in store.document.values() if d["source_id"] == "ema-psusa"]
    assert len(docs) == 9 and all(d["is_backfill"] for d in docs)
    assert store.source["ema-psusa"]["last_ok_at"] is not None
    ctx.close()


def test_run_deadline_leaves_sources_for_the_next_run(tmp_path):
    server = Server()
    store, ctx, runner, _ = setup(tmp_path, server)
    runner.deadline, runner.clock = 100.0, lambda: 100.0
    assert runner.run([SRC])
    assert runner.skipped == ["ema-psusa"] and store.source_run == {}
    ctx.close()


def test_a_crashed_run_is_never_recorded_as_ok(tmp_path, monkeypatch):
    from collectors import run as run_mod

    monkeypatch.chdir(tmp_path)
    finished: list[bool] = []
    monkeypatch.setattr(MemoryStore, "finish_run", lambda self, run_id, ok: finished.append(ok))

    def boom(self, sources):
        raise RuntimeError("database went away")

    monkeypatch.setattr(run_mod.Runner, "run", boom)
    with pytest.raises(RuntimeError):
        run_mod.main(["--no-db", "--source", "ema-psusa"])
    assert finished == [False]


@pytest.mark.parametrize(("argv", "event", "trigger"), [
    (["--schedule", "12h"], "schedule", "cron"),
    (["--schedule", "4h"], "repository_dispatch", "cron"),
    (["--schedule", "daily"], "workflow_dispatch", "manual"),
    (["--backfill", "12"], "workflow_dispatch", "backfill"),
    (["--backfill"], "workflow_dispatch", "backfill"),
])
def test_each_run_records_what_started_it(tmp_path, monkeypatch, argv, event, trigger):
    # Every run was recorded as a backfill, so the 12h run of 5 Nov 2026 22:53 UTC passed for the last 12-month
    # backfill and migration 0034 marked levofloxacin's words as already checked against the stored notices.
    from collectors import run as run_mod

    class Recorded(Exception):
        pass

    def create_run(self, recorded_trigger, git_sha, schedule=None):
        raise Recorded(recorded_trigger)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setattr(MemoryStore, "create_run", create_run)
    with pytest.raises(Recorded) as recorded:
        run_mod.main(["--no-db", *argv])
    assert recorded.value.args[0] == trigger


def test_nul_characters_never_reach_postgres():
    from collectors.core.db import _dumps, clean

    assert clean({"t": "Rote-Hand-Brief\x00", "l": ["a\x00", 1], "n": None}) == {
        "t": "Rote-Hand-Brief", "l": ["a", 1], "n": None}
    assert clean(("x\x00y",)) == ("xy",)
    assert _dumps({"t": "a\x00b"}) == '{"t": "ab"}'


def test_a_secret_in_a_failure_never_reaches_the_screening_log_or_alert(tmp_path):
    # source_run.error is readable by every user and health alerts go to Telegram: no api_key there.
    secret = "NCBI0123456789abcdefSECRET"

    class Parser:
        @staticmethod
        def list_items(ctx, src):
            raise RuntimeError(f"connect failed for https://eutils.ncbi.nlm.nih.gov/x?db=pubmed&api_key={secret}")

    server = Server()
    store, ctx, _, _ = setup(tmp_path, server)
    notifier = Notifier(store, store.settings(), telegram=ExplodingTelegram())
    runner = Runner(store, ctx, notifier, store.settings(), parser_loader=lambda name: Parser)
    for _ in range(DOWN_AFTER):
        stats = runner.run_source(SRC)
    assert stats.failed and "api_key=<redacted>" in stats.error
    assert all(secret not in (sr["error"] or "") for sr in store.source_run.values())
    health = [n for n in store.notification if n["kind"] == "health"]
    assert health and all(secret not in str(n) for n in health)
    ctx.close()


def test_after_store_hears_only_items_now_in_the_database(tmp_path, monkeypatch):
    # The mailbox marks a message processed from this set; a failed item must not be in it.
    from collectors.core.models import Item

    heard: list[set[str]] = []

    class Parser:
        @staticmethod
        def list_items(ctx, src):
            return [Item(external_id=x, url=f"https://example.org/{x}", title=x, published=date.today(),
                         doc_type="newsletter", lang="en") for x in ("ok", "broken")]

        @staticmethod
        def after_store(ctx, src, items, stored):
            heard.append(set(stored))

    server = Server()
    store, ctx, _, _ = setup(tmp_path, server)
    runner = Runner(store, ctx, Notifier(store, store.settings()), store.settings(),
                    parser_loader=lambda name: Parser)
    real = runner.process_item

    def process(src, module, item, **kw):
        if item.external_id == "broken":
            raise RuntimeError("could not store")
        return real(src, module, item, **kw)

    monkeypatch.setattr(runner, "process_item", process)
    runner.run_source(SRC)
    assert heard == [{"ok"}]
    ctx.close()


def test_a_source_not_set_up_is_reported_as_such(tmp_path):
    from collectors.core.context import NotSetUp

    class Parser:
        @staticmethod
        def list_items(ctx, src):
            raise NotSetUp("uae-mohap has no reading rules yet.")

    server = Server()
    store, ctx, _, _ = setup(tmp_path, server)
    runner = Runner(store, ctx, Notifier(store, store.settings()), store.settings(),
                    parser_loader=lambda name: Parser)
    stats = runner.run_source(SRC)
    assert stats.failed
    health = [n for n in store.notification if n["kind"] == "health"]
    assert health and "Not set up yet: uae-mohap has no reading rules yet." in str(health[-1])
    assert "changed shape" not in str(health[-1])
    ctx.close()


def test_each_run_records_the_slot_it_served(tmp_path):
    store = MemoryStore()
    rid = store.create_run("cron", "sha", "12h")
    assert store.run[rid]["schedule"] == "12h"


def test_a_misread_future_date_never_becomes_the_source_last_item():
    # last_item_at only moves forward, so one future date (a day/month misread) would stick for good
    from datetime import timedelta
    from types import SimpleNamespace

    today = date.today()
    items = [SimpleNamespace(published=today - timedelta(days=3)), SimpleNamespace(published=None),
             SimpleNamespace(published=today + timedelta(days=35))]
    assert latest_published(items) == today - timedelta(days=3)
    assert latest_published([SimpleNamespace(published=None)]) is None


def test_an_attachment_behind_a_bot_check_is_skipped_not_the_source(tmp_path):
    # 5 Nov 2026: an ANSM vaccine notice linked a PDF on sante.gouv.fr, whose bot check marked the whole
    # ANSM source "blocked" and stopped the notices behind it.
    from collectors.core.context import SourceBlocked
    from collectors.core.models import Fetched, Item

    class Ctx:
        def get(self, url, accept=None):
            if "sante.gouv.fr" in url:
                raise SourceBlocked(f"bot check at {url} (HTTP 200)")
            return Fetched(200, url, b"<html><body><main>Lornoxicam lettre</main></body></html>",
                           "text/html; charset=utf-8")

    store = MemoryStore()
    runner = Runner(store, Ctx(), Notifier(store, store.settings(), telegram=ExplodingTelegram()),
                    store.settings())
    item = Item(external_id="x", url="https://ansm.sante.fr/x", title="x", published=None,
                doc_type="safety_alert", lang="fr",
                attachment_urls=["https://sante.gouv.fr/IMG/pdf/recommandations_voyageurs.pdf",
                                 "https://ansm.sante.fr/uploads/lettre.html"])
    atts = runner._attachments(item, "fr")
    assert [a["url"] for a in atts] == ["https://ansm.sante.fr/uploads/lettre.html"]
    assert "Lornoxicam" in atts[0]["text"]


def test_a_source_removed_during_the_run_is_skipped_and_the_run_goes_on(tmp_path):
    # 0100: a source never read can be removed on Sources while a run that listed it is going. Postgres then
    # refuses its source_run row (the foreign key); the runner skips it instead of stopping the run.
    server = Server()
    store, ctx, runner, ing_id = setup(tmp_path, server)
    del store.source[SRC.id]
    real = store.start_source_run

    def refused(run_id, source_id):
        if source_id not in store.source:
            raise RuntimeError('insert or update on table "source_run" violates foreign key constraint')
        return real(run_id, source_id)

    store.start_source_run = refused
    stats = runner.run_source(SRC)
    assert not stats.failed and stats.seen == 0
    assert not store.source_run                                   # nothing written for it
    assert runner.run([SRC]) is True                              # the run is not failed by it

    # A refusal for any other reason still stops the source as before.
    sync_catalogue(store)

    def broken(run_id, source_id):
        raise RuntimeError("database down")

    store.start_source_run = broken
    with pytest.raises(RuntimeError, match="database down"):
        runner.run_source(SRC)
