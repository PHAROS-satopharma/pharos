"""Clinical trials from ClinicalTrials.gov (migration 0067): the search, what is kept of a study, and what is
fetched again. The API's answers are recorded in tests/fixtures/trials (two carvedilol studies with results and
one recruiting, the sponsor-investigator's name replaced); nothing leaves the machine."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

from collectors import trials

FIX = Path(__file__).parent / "fixtures" / "trials"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


STUDIES = {s["protocolSection"]["identificationModule"]["nctId"]: s for s in load("studies.json")["studies"]}


class FakeApi:
    """search_1 then search_2 for a search; the recorded studies for a fetch by id."""

    def __init__(self):
        self.asked: list[dict] = []

    def __call__(self, params: dict) -> dict:
        self.asked.append(params)
        if "query.intr" in params:
            return load("search_2.json" if params.get("pageToken") else "search_1.json")
        ids = params["filter.ids"].split(",")
        return {"studies": [STUDIES[i] for i in ids if i in STUDIES]}


class FakeDb:
    def __init__(self, rows=None):
        self.rows, self.done = rows or {}, []

    def fetchall(self, sql, params=None):
        for key, rows in self.rows.items():
            if key in sql:
                return rows
        return []

    def execute(self, sql, params=None):
        self.done.append((" ".join(sql.split())[:40], params))

    @contextmanager
    def transaction(self):
        yield self

    def sql(self, start: str) -> list:
        return [p for s, p in self.done if s.startswith(start)]


CARVEDILOL = [{"id": "ing-1", "inn_en": "carvedilol", "terms": ["Coreg", "CARVEDILOL", "カルベジロール", "Dil", "Carvedilol phosphate"]}]


# ───────────────────────────── the search ─────────────────────────────
def test_the_english_names_are_searched_once_each_and_quoted():
    got = trials.names("carvedilol", CARVEDILOL[0]["terms"])
    assert got == ["carvedilol", "Carvedilol phosphate", "Coreg"]     # no Japanese, no 3-letter brand, no repeat
    assert trials.expression(got) == '"carvedilol" OR "Carvedilol phosphate" OR "Coreg"'
    assert trials.names('say "AND"', []) == ["say AND"]


# ───────────────────────────── what is kept ─────────────────────────────
def test_a_study_with_serious_events_is_kept_as_published():
    t = trials.parse_study(STUDIES["NCT00292162"])
    assert {k: t[k] for k in ("nct_id", "title", "phase", "status", "start_date", "completion_date", "sponsor",
                              "enrolment", "enrolment_type", "has_results", "results_posted_on", "last_update_on")} == {
        "nct_id": "NCT00292162", "title": "Curing Atrial Fibrillation in Heart Failure", "phase": ["NA"],
        "status": "COMPLETED", "start_date": "2007-01", "completion_date": "2009-07",
        "sponsor": "NHS Greater Glasgow and Clyde", "enrolment": 41, "enrolment_type": "ACTUAL", "has_results": True,
        "results_posted_on": "2012-06-01", "last_update_on": "2012-06-01"}
    by_term = {e["term"]: e for e in t["events"]}
    assert set(by_term) == {"Stroke", "Cardiac tamponade", "heart failure hospitalisation"}  # the sponsor's words
    tamponade = by_term["Cardiac tamponade"]
    assert tamponade["serious"] and tamponade["organ_system"] == "Cardiac disorders"
    assert (tamponade["affected"], tamponade["at_risk"]) == (2, 41)                 # summed over both groups
    assert [g["group"] for g in tamponade["groups"]] == ["Medical Therapy", "Radiofrequency Ablation"]
    assert [g["affected"] for g in tamponade["groups"]] == [0, 2]


def test_other_events_and_a_study_without_results():
    other = trials.parse_study(STUDIES["NCT02717507"])["events"]
    assert {(e["term"], e["serious"], e["affected"], e["at_risk"]) for e in other} == {
        ("Dyspnea", False, 1, 182), ("Arthralgia", False, 1, 182)}
    t = trials.parse_study(STUDIES["NCT06078436"])
    assert t["status"] == "RECRUITING" and not t["has_results"] and t["events"] == []
    assert t["results_posted_on"] is None and t["enrolment_type"] == "ESTIMATED"
    assert trials.parse_study({"protocolSection": {}}) is None


def test_a_term_given_twice_is_one_row_and_a_missing_count_is_none():
    module = {"eventGroups": [{"id": "EG000", "title": "Drug"}, {"id": "EG001", "title": "Placebo"}],
              "seriousEvents": [
                  {"term": "Syncope", "organSystem": "Nervous system disorders",
                   "stats": [{"groupId": "EG000", "numAffected": 2, "numAtRisk": 50},
                             {"groupId": "EG001", "numAffected": 1, "numAtRisk": 48}]},
                  {"term": "Syncope", "organSystem": "Nervous system disorders",
                   "stats": [{"groupId": "EG000", "numAffected": 1, "numAtRisk": 50}, {"groupId": "EG001"}]}],
              "otherEvents": [{"term": "Syncope", "organSystem": "Nervous system disorders",
                               "stats": [{"groupId": "EG000", "numEvents": 3}]}]}
    serious, other = sorted(trials.events(module), key=lambda e: not e["serious"])
    assert (serious["affected"], serious["at_risk"]) == (4, 98)          # the people at risk once per group
    assert serious["groups"] == [{"group": "Drug", "affected": 3, "at_risk": 50},
                                 {"group": "Placebo", "affected": 1, "at_risk": 48}]
    assert (other["affected"], other["at_risk"]) == (0, None)


# ───────────────────────────── a run ─────────────────────────────
def test_only_new_or_updated_studies_are_fetched_and_the_links_follow_the_search():
    known = [{"nct_id": "NCT02717507", "last_update": "2025-04-23"},      # unchanged
             {"nct_id": "NCT00292162", "last_update": "2011-01-01"}]      # updated since
    db = FakeDb({"from ingredient i": CARVEDILOL, "from trial where nct_id": known})
    api = FakeApi()
    words = trials.run(db, get=api)
    assert words == "1 ingredients searched, 2 studies fetched, 1 unchanged"
    searches = [a for a in api.asked if "query.intr" in a]
    assert [a.get("pageToken") for a in searches] == [None, "ZVNj7o2Elu8o3lpyCMqxo7LumpOQJJxtYvih3f0ZkA"]
    assert searches[0]["query.intr"] == '"carvedilol" OR "Carvedilol phosphate" OR "Coreg"'
    fetched = [a["filter.ids"] for a in api.asked if "filter.ids" in a]
    assert fetched == ["NCT00292162,NCT06078436"]
    assert [p["nct_id"] for p in db.sql("insert into trial (nct_id")] == ["NCT00292162", "NCT06078436"]
    assert [p["nct_id"] for p in db.sql("delete from trial_event")] == ["NCT00292162", "NCT06078436"]
    events = db.sql("insert into trial_event")
    assert len(events) == 1 and len(json.loads(events[0]["events"])) == 3     # no events, no insert
    ids = ["NCT00292162", "NCT02717507", "NCT06078436"]
    assert db.sql("insert into trial_ingredient") == [{"i": "ing-1", "ids": ids}]
    assert db.sql("delete from trial_ingredient") == [{"i": "ing-1", "ids": ids}]
    assert db.sql("insert into trial_search") == [{"i": "ing-1", "names": ["carvedilol", "Carvedilol phosphate",
                                                                          "Coreg"]}]
    assert len(db.sql("delete from trial t")) == 1                           # the studies no ingredient links


def test_a_study_two_ingredients_name_is_fetched_once():
    two = CARVEDILOL + [{"id": "ing-2", "inn_en": "carvedilol phosphate", "terms": []}]
    db = FakeDb({"from ingredient i": two})
    api = FakeApi()
    assert trials.run(db, get=api) == "2 ingredients searched, 3 studies fetched, 0 unchanged"
    assert len([a for a in api.asked if "filter.ids" in a]) == 1
    assert [p["i"] for p in db.sql("insert into trial_ingredient")] == ["ing-1", "ing-2"]


def test_a_search_cut_short_unlinks_nothing(monkeypatch):
    monkeypatch.setattr(trials, "MAX_PAGES", 1)
    db = FakeDb({"from ingredient i": CARVEDILOL})
    trials.run(db, get=FakeApi())
    assert db.sql("insert into trial_ingredient") and not db.sql("delete from trial_ingredient")


def test_a_failed_search_changes_nothing_and_is_counted():
    db = FakeDb({"from ingredient i": CARVEDILOL})

    def down(params):
        raise TimeoutError

    assert trials.run(db, get=down) == "0 ingredients searched, 0 studies fetched, 0 unchanged, 1 to try again"
    assert not db.sql("insert into trial") and not db.sql("delete from trial_ingredient")


def test_no_ingredient_asks_nothing():
    assert trials.run(FakeDb(), get=lambda p: 1 / 0) == "no active ingredient"
