"""The weekly label watch is one job per label source (label-watch.yml, 13 Nov 2026).

Until then the seventeen sources shared the weekly collection's 78 minutes, about 4.6 each: on 9 Nov DailyMed, CIMA
and the MHRA spent all of it on their product lists and read no label. These tests hold the workflow, the list of
sources and the database's back-up timer together.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from collectors.spc.run import MODULES

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TEXT = (WORKFLOWS / "label-watch.yml").read_text(encoding="utf-8")
FLOW = yaml.safe_load(TEXT)
ON = FLOW.get("on") or FLOW.get(True)          # YAML 1.1 reads the key "on" as true
JOB = FLOW["jobs"]["watch"]


def _crons(name: str) -> list[str]:
    flow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    on = flow.get("on") or flow.get(True)
    return [c["cron"] for c in on.get("schedule") or []]


def test_every_label_source_has_its_own_job():
    lists = [json.loads(m) for m in re.findall(r"fromJSON\('(\[\"spc-[^']*\])'\)", TEXT)]
    assert len(lists) == 2                      # the matrix, and the check of a source asked for by hand
    for sources in lists:
        assert sources == sorted(MODULES)
    assert JOB["strategy"]["fail-fast"] is False


def test_each_job_has_hours_and_stops_before_github_kills_it():
    budget = int(JOB["env"]["PHAROS_TIME_BUDGET_MIN"])
    assert budget >= 300                        # DailyMed's 1,911 labels take about 80 minutes
    assert JOB["timeout-minutes"] - budget >= 10
    assert JOB["timeout-minutes"] <= 360        # GitHub's limit for one job
    step = next(s for s in JOB["steps"] if s.get("name") == "Label watch")
    assert "--schedule weekly --spc-source" in step["run"]


def test_the_label_watch_never_holds_the_collection_queue():
    assert FLOW["concurrency"] == {"group": "label-watch", "cancel-in-progress": False}


def test_monday_is_the_label_watch_not_the_collection():
    assert _crons("label-watch.yml") == ["23 3 * * 1"]
    assert "23 3 * * 1" not in _crons("collect.yml")


def test_the_back_up_timer_starts_the_label_watch():
    assert ON["repository_dispatch"]["types"] == ["label-watch"]
    sql = (ROOT / "supabase" / "migrations" / "0112_label_watch_kick.sql").read_text(encoding="utf-8")
    assert "case when p_schedule = 'weekly' then 'label-watch' else 'collect' end" in sql
    assert "revoke all on function ops_kick_collect(text) from public, anon, authenticated" in sql
