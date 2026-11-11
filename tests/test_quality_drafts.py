"""A drafted root cause and CAPA (migration 0109, collectors/quality_drafts.py): the facts given to the reader are
only what is recorded; the answer is the four fields; a failure is recorded and tried again only when it is worth
it. The SQL of the table and its functions is tested in supabase/tests/quality_drafts.sql."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest

from collectors import quality_drafts as qd

DEVIATION = {
    "ref": "D001/2026", "title": "Late case entry", "description": "A serious case was entered on day 16.",
    "occurred_on": date(2026, 11, 2), "detected_on": date(2026, 11, 4), "level": 2, "patient_safety": True,
    "regulatory_compliance": True, "document_quality": False, "inv_cause": "The case officer was on leave.",
    "inv_people_time": None, "inv_reoccur": None, "inv_similar": None, "inv_other_impact": None,
    "inv_training": None, "root_cause": None, "status": "investigating",
    "capas": json.dumps([{"ref": "CAPA-001/2026", "corrective": "Enter the case", "preventive": None,
                          "status": "draft"}]),
}
OBSERVATION = {
    "number": 2, "text": "The signal log was not reviewed monthly.", "grade": "major", "root_cause": None,
    "kind": "external", "audit_title": "Partner Pharma 2026", "auditor": "Partner Pharma (MAH)",
    "report_received_on": date(2026, 11, 1), "capas": [],
}
ANSWER = {"root_cause": "No deputy was named for case entry.", "corrective_action": "Enter the case today.",
          "preventive_action": "Name a deputy within 5 working days.", "to_check": "Who covered the leave."}


def test_the_facts_are_only_what_is_recorded_on_the_deviation():
    text = qd.facts("deviation", DEVIATION)
    for words in ("D001/2026: Late case entry", "entered on day 16", "Happened on: 2026-11-02",
                  "patient safety, regulatory compliance", "2 (may affect regulatory compliance)",
                  "What was the cause? The case officer was on leave.",
                  "Who was involved, the time and the duration? (not answered yet)",
                  "Root cause written so far: (none yet)", "CAPA-001/2026 (draft); corrective: Enter the case"):
        assert words in text, words
    assert "document quality" not in text


def test_the_facts_of_an_observation_name_the_audit_and_its_grade():
    text = qd.facts("observation", OBSERVATION)
    assert 'An external audit, "Partner Pharma 2026", by Partner Pharma (MAH)' in text
    assert "Observation 2, graded major: The signal log was not reviewed monthly." in text
    assert "CAPAs already recorded: none." in text


def test_the_rules_keep_the_draft_to_the_facts():
    assert "Never invent" in qd.SYSTEM and "to_check" in qd.SYSTEM
    assert "never a person's name" in qd.SYSTEM
    assert set(qd.SCHEMA["required"]) == {"root_cause", "corrective_action", "preventive_action", "to_check"}


class FakeMessages:
    def __init__(self, text: str, stop: str = "end_turn"):
        self.text, self.stop, self.calls = text, stop, []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason=self.stop, model="claude-opus-5-5",
                               content=[SimpleNamespace(type="text", text=self.text)])


def test_the_reader_is_asked_for_the_four_fields_in_its_schema():
    msgs = FakeMessages(json.dumps(ANSWER))
    fields, model = qd.call_drafter("facts", client=SimpleNamespace(messages=msgs))
    assert fields == ANSWER and model == "claude-opus-5-5"
    call = msgs.calls[0]
    assert call["model"] == qd.MODEL and call["system"] == qd.SYSTEM
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": qd.SCHEMA}


@pytest.mark.parametrize("text,stop,passing", [
    (json.dumps({**ANSWER, "root_cause": " "}), "end_turn", True),
    ("{not json", "end_turn", True),
    ("", "refusal", False),
    ("", "max_tokens", True),
])
def test_an_answer_that_cannot_be_used_is_a_failure_in_her_words(text, stop, passing):
    with pytest.raises(qd.DraftFailed) as e:
        qd.call_drafter("facts", client=SimpleNamespace(messages=FakeMessages(text, stop)))
    assert e.value.passing is passing and str(e.value)


class FakeDb:
    """Answers the claim, the record and the writes of draft_one; keeps every write."""

    def __init__(self, claimed: dict | None, record: dict | None):
        self.claimed, self.record, self.writes = claimed, record, []

    def fetchone(self, sql, params=None):
        if "update quality_draft set status = 'drafting'" in sql:
            return self.claimed
        return self.record

    def execute(self, sql, params=None):
        self.writes.append((sql, params))


def claimed(kind="deviation", attempts=1):
    return {"id": "q1", "record_kind": kind, "record_id": "r1", "attempts": attempts}


def test_a_draft_is_written_back_ready_with_the_model():
    db = FakeDb(claimed(), DEVIATION)
    seen = []
    status = qd.draft_one(db, "q1", drafter=lambda text: (seen.append(text) or (ANSWER, "claude-opus-5-5")))
    assert status == "ready" and "D001/2026" in seen[0]
    sql, p = db.writes[-1]
    assert "status = 'ready'" in sql
    assert (p["r"], p["c"], p["p"], p["t"], p["m"]) == (ANSWER["root_cause"], ANSWER["corrective_action"],
                                                        ANSWER["preventive_action"], ANSWER["to_check"],
                                                        "claude-opus-5-5")


def test_a_draft_not_waiting_is_left_alone():
    db = FakeDb(None, DEVIATION)
    assert qd.draft_one(db, "q1", drafter=lambda t: pytest.fail("never asked")) == "skipped"
    assert db.writes == []


def test_a_passing_failure_waits_for_the_next_run_and_the_last_attempt_fails():
    def unreachable(text):
        raise qd.DraftFailed("The reader could not be reached (APIConnectionError). Try again.", passing=True)

    db = FakeDb(claimed(attempts=1), DEVIATION)
    assert qd.draft_one(db, "q1", drafter=unreachable) == "queued"
    assert db.writes[-1][1]["s"] == "queued"
    db = FakeDb(claimed(attempts=qd.MAX_ATTEMPTS), DEVIATION)
    assert qd.draft_one(db, "q1", drafter=unreachable) == "failed"
    assert db.writes[-1][1]["s"] == "failed" and "could not be reached" in db.writes[-1][1]["e"]


def test_a_record_gone_or_a_refusal_fails_at_once():
    db = FakeDb(claimed(), None)
    assert qd.draft_one(db, "q1", drafter=lambda t: pytest.fail("never asked")) == "failed"
    assert db.writes[-1][1]["e"] == "The record is no longer there."

    def refused(text):
        raise qd.DraftFailed("The reader declined to draft this. Write it by hand.")

    db = FakeDb(claimed("observation"), OBSERVATION)
    assert qd.draft_one(db, "q1", drafter=refused) == "failed"


def test_the_command_needs_a_draft_id_or_waiting():
    with pytest.raises(SystemExit):
        qd.main([])
    with pytest.raises(SystemExit):
        qd.main(["--draft", "not-an-id"])
