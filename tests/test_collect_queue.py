"""The readiness runs are never lost in GitHub's queue (6 Nov 2026).

GitHub keeps only ONE waiting run per concurrency group: a newer run queued behind a running one cancels the run
already waiting. Both literature slots of 6 Nov were lost that way, and a 285-minute backfill held the shared
"collectors" group for hours. A backfill now has its own group (backfill.yml), and the database asks again every
hour for a readiness slot whose run never started (supabase/migrations/0084, tested in
supabase/tests/readiness_kick.sql). These tests hold the workflows and the timer's slot times together.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import yaml

from collectors.core.registry import load_catalogue
from collectors.merge import merge_document
from collectors.run import select_sources
from tests.test_merge import add_doc, store_with_regulators

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
MIGRATION = ROOT / "supabase" / "migrations" / "0084_readiness_kick.sql"
_, SOURCES, _ = load_catalogue()


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _group(name: str) -> str | None:
    return (_workflow(name).get("concurrency") or {}).get("group")


def _crons(name: str) -> list[str]:
    on = _workflow(name).get("on") or _workflow(name).get(True)    # YAML 1.1 reads the key "on" as true
    return [c["cron"] for c in on.get("schedule") or []]


def test_a_backfill_never_holds_or_empties_the_collection_queue():
    assert _group("backfill.yml") == "backfill"
    for name in ("collect.yml", "rematch.yml", "audit.yml"):
        # the check of the past and the matching audit write what a collection reads: never at the same time
        assert _group(name) == "collectors", name
    for path in WORKFLOWS.glob("*.yml"):
        if path.name not in ("collect.yml", "rematch.yml", "audit.yml"):
            assert _group(path.name) != "collectors", f"{path.name} would cancel a waiting readiness run"
    assert _workflow("backfill.yml")["concurrency"]["cancel-in-progress"] is False


def test_the_readiness_timer_retries_the_slots_collect_yml_runs():
    sql = MIGRATION.read_text(encoding="utf-8")
    slots = re.findall(r"\('(daily|literature)',\s*time '(\d\d):(\d\d)'\)", sql)
    assert sorted(slots) == [("daily", "02", "31"), ("literature", "10", "41"), ("literature", "18", "41")]
    crons = _crons("collect.yml")
    for schedule, hh, mm in slots:
        assert any(re.fullmatch(rf"{int(mm)} (\S*,)?{int(hh)}(,\S*)? \* \* \*", c) for c in crons), (schedule, hh, mm)
    # the timer asks GitHub every hour, after the 4-hour (:07) and before the 12-hour (:37) back-ups
    assert "cron.schedule('pharos-kick-readiness', '29 * * * *'" in sql
    # 0007's once-a-day daily back-up would ask for the 02:31 slot a second time
    assert "cron.unschedule(jobid) from cron.job where jobname = 'pharos-kick-daily'" in sql


def test_a_literature_run_the_timer_starts_gets_the_literature_timeout():
    job = _workflow("collect.yml")["jobs"]["collect"]
    timeout = job["timeout-minutes"]
    # a literature run is the drug classes, NCBI and Europe PMC, the check of the past (15) and a pack (20): 80 minutes
    assert "github.event.client_payload.schedule == 'literature') && 80" in timeout
    assert "github.event.client_payload.schedule == 'daily'" in timeout
    # the run says which slot it served, so the timer knows it started (run.schedule)
    which = next(s for s in job["steps"] if s.get("id") == "which")
    assert "github.event.client_payload.schedule" in which["env"]["INPUT_SCHEDULE"]


def test_a_backfill_leaves_the_mailbox_to_the_regular_run():
    on = [dataclasses.replace(s, enabled=True) for s in SOURCES]
    mail = {s.id for s in on if s.channel == "email"}
    assert {"fimea-email", "tga-email", "fda-email", "famhp-email", "hc-email"} <= mail
    backfill = {s.id for s in select_sources(on, "all", None, True)}
    assert backfill and not backfill & mail
    assert "pubmed" in backfill and "ema-psusa" in backfill
    # the regular runs still read it
    assert mail <= {s.id for s in select_sources(on, "all", None, False)}
    assert {s.id for s in on if s.channel == "email" and s.schedule == "4h"} <= \
        {s.id for s in select_sources(on, "4h", None, False)}
    # a backfill of one named source is the admin's choice and still runs it
    assert [s.id for s in select_sources(on, "all", "fimea-email", True)] == ["fimea-email"]


def test_two_runs_never_place_documents_among_the_issues_at_once():
    # A backfill and a collection each reading the other's uncommitted anchor or copy would give one event two
    # issues: merge_document takes the database's merge lock (Store.lock_issue_merge, held to the end of the
    # document's transaction) before it reads the candidate issues.
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "lornoxicam: serious skin reactions")
    copy = add_doc(s, "bfarm-rhb", "Rote-Hand-Brief zu Xefo (Lornoxicam)", date(2026, 10, 6), "Lornoxicam.")
    merge_document(s, anchor, mahs=[])
    merge_document(s, copy, mahs=[])
    assert s.merge_locks == 2
    # a paper merges with nothing and reads no other issue: no lock, thousands of papers a year
    paper = add_doc(s, "ema-dhpc", "A lornoxicam case report", date(2026, 10, 2), "Lornoxicam.", doc_type="literature")
    merge_document(s, paper, mahs=[])
    assert s.merge_locks == 2
