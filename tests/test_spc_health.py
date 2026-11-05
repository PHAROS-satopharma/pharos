"""The weekly label watch writes its line in the screening log and its health on the Sources page,
like every other source: before this, all six label sources stayed "Not checked yet"."""

from __future__ import annotations

from types import SimpleNamespace

from collectors.core.memstore import MemoryStore
from collectors.spc import run as spc_run
from tests.fakes_a2 import SpcDb

ING = {"id": "ing-1", "inn_en": "lornoxicam", "atc_code": "M01AC05", "terms": {"en": ["lornoxicam"]}}


def _store(*source_ids: str) -> MemoryStore:
    store = MemoryStore()
    for sid in source_ids:
        store.source[sid] = {"id": sid, "kind": "spc", "enabled": True, "health": "unknown",
                             "consecutive_failures": 0, "last_ok_at": None, "last_item_at": None}
    return store


def _run(monkeypatch, store, modules: dict) -> None:
    monkeypatch.setattr(spc_run, "_ingredients", lambda db, ids: [dict(ING)])
    monkeypatch.setattr(spc_run, "_sources", lambda db: list(modules))
    monkeypatch.setattr(spc_run.importlib, "import_module",
                        lambda name: modules[next(k for k in modules if spc_run.MODULES[k] in name)])
    spc_run.run_spc(SimpleNamespace(run_id="run-1"), db=SpcDb(), store=store)


def _fails(ctx, ing):
    raise RuntimeError("HTTP 404 for https://www.ema.europa.eu/en/documents/report/x.json")


def test_every_label_source_gets_a_screening_log_row(monkeypatch):
    store = _store("spc-ema-epar", "spc-dailymed")
    _run(monkeypatch, store, {"spc-ema-epar": SimpleNamespace(discover=_fails),
                              "spc-dailymed": SimpleNamespace(discover=lambda ctx, ing: [])})
    rows = {r["source_id"]: r for r in store.source_run.values()}
    assert set(rows) == {"spc-ema-epar", "spc-dailymed"}
    assert all(r["run_id"] == "run-1" and "finished_at" in r for r in rows.values())
    assert "HTTP 404" in rows["spc-ema-epar"]["error"]
    assert rows["spc-dailymed"]["error"] is None and rows["spc-dailymed"]["items_seen"] == 0
    assert store.source["spc-ema-epar"]["health"] == "degraded"
    assert store.source["spc-dailymed"]["health"] == "ok"
    assert store.source["spc-dailymed"]["last_ok_at"] is not None


def test_three_failed_weeks_in_a_row_is_down_and_one_good_week_clears_it(monkeypatch):
    store = _store("spc-ema-epar")
    for _ in range(3):
        _run(monkeypatch, store, {"spc-ema-epar": SimpleNamespace(discover=_fails)})
    assert store.source["spc-ema-epar"]["health"] == "down"
    assert store.source["spc-ema-epar"]["consecutive_failures"] == 3
    _run(monkeypatch, store, {"spc-ema-epar": SimpleNamespace(discover=lambda ctx, ing: [])})
    assert store.source["spc-ema-epar"]["health"] == "ok"
    assert store.source["spc-ema-epar"]["consecutive_failures"] == 0


def test_without_a_store_nothing_is_recorded(monkeypatch):
    monkeypatch.setattr(spc_run, "_ingredients", lambda db, ids: [dict(ING)])
    monkeypatch.setattr(spc_run, "_sources", lambda db: ["spc-ema-epar"])
    monkeypatch.setattr(spc_run.importlib, "import_module", lambda name: SimpleNamespace(discover=_fails))
    assert spc_run.run_spc(SimpleNamespace(run_id="run-1"), db=SpcDb()) == []
