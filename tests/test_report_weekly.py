"""The weekly screening report (Dr Sama's review, 6 Nov 2026): one Cairo week, Sunday to Saturday, read from the
Ingredients screen's own functions, in six sections, as a PDF and an Excel file."""
import io
import os
import re
import shutil
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

from collectors import report, report_weekly as rw
from collectors.core.memstore import MemoryStore
from collectors.report import copyright_line, render_footer
from collectors.report_weekly import Week

ROOT = Path(__file__).resolve().parents[1]
NOV1 = Week(date(2026, 11, 1))
UTC = timezone.utc


# ───────────────────────────── the week ─────────────────────────────

def test_a_week_runs_sunday_to_saturday_in_cairo_time():
    assert NOV1.end == date(2026, 11, 7)
    assert NOV1.slug == "2026-11-01"
    assert NOV1.name == "Weekly screening report"
    # winter (UTC+2)
    assert NOV1.bounds_utc() == (datetime(2026, 10, 31, 22, tzinfo=UTC), datetime(2026, 11, 7, 22, tzinfo=UTC))
    # summer (UTC+3)
    assert Week(date(2026, 8, 2)).bounds_utc() == (datetime(2026, 8, 1, 21, tzinfo=UTC),
                                                   datetime(2026, 8, 8, 21, tzinfo=UTC))
    # the week summer time ends in (the last Thursday of October): Sunday 00:00 at +3, the next at +2
    assert Week(date(2026, 10, 25)).bounds_utc() == (datetime(2026, 10, 24, 21, tzinfo=UTC),
                                                     datetime(2026, 10, 31, 22, tzinfo=UTC))


def test_the_default_week_is_the_last_one_that_ended_in_cairo():
    # Sunday 8 Nov 2026 at 05:00 Cairo, when the schedule makes it
    assert rw.last_complete_week(datetime(2026, 11, 8, 3, tzinfo=UTC)) == NOV1
    # Saturday 23:59 Cairo: that week has not ended yet
    assert rw.last_complete_week(datetime(2026, 11, 7, 21, 59, tzinfo=UTC)).start == date(2026, 10, 25)
    # Sunday 00:00 Cairo, still Saturday in UTC
    assert rw.last_complete_week(datetime(2026, 11, 7, 22, 0, tzinfo=UTC)) == NOV1
    # in the middle of the week
    assert rw.last_complete_week(datetime(2026, 11, 11, 9, tzinfo=UTC)) == NOV1


def test_a_week_must_start_on_a_sunday():
    with pytest.raises(ValueError, match=r"2026-11-02 is a Monday.*2026-11-01 starts that week"):
        rw.week_starting(date(2026, 11, 2))
    assert rw.week_starting(date(2026, 11, 1)) == NOV1
    assert rw.sunday_of(date(2026, 11, 7)) == date(2026, 11, 1)
    assert rw.sunday_of(date(2026, 11, 1)) == date(2026, 11, 1)


def test_the_command_refuses_a_wrong_week_before_it_connects(capsys):
    with pytest.raises(SystemExit) as e:
        report.main(["--week", "2026-11-04"])
    assert e.value.code == 2
    assert "is a Wednesday" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        report.main(["--week", "2026-11-01", "--month", "2026-10"])
    assert e.value.code == 2


def test_the_footer_label_is_never_longer_than_the_monthly_one():
    """The running foot is one line beside the credit and the page number; a longer label is cut with an
    ellipsis (the full week label was: CI printed "Sun 1 Nov – Sat 7 …")."""
    longest_month = len(report.Month(date(2026, 9, 1)).footer)
    assert NOV1.footer == "Weekly report · 1 Nov – 7 Nov 2026"
    across = Week(date(2026, 12, 27))
    assert across.footer == "Weekly report · 27 Dec 2026 – 2 Jan 2027"
    assert len(across.footer) <= longest_month
    assert "PHAROS · Weekly report · 1 Nov – 7 Nov 2026" in render_footer(NOV1)
    assert "PHAROS · Monthly screening report · October 2026" in render_footer(report.Month(date(2026, 10, 1)))


def test_week_labels():
    assert NOV1.label == "Sun 1 Nov – Sat 7 Nov 2026"
    assert Week(date(2026, 10, 25)).label == "Sun 25 Oct – Sat 31 Oct 2026"
    assert Week(date(2026, 12, 27)).label == "Sun 27 Dec 2026 – Sat 2 Jan 2027"


# ───────────────────────────── the answers, as the Ingredients screen ─────────────────────────────

def _source(sid, reg, **extra):
    return {"id": sid, "regulator_id": reg, "kind": "safety", "channel": "html",
            "url": f"https://example.test/{sid}", "page_url": None, "enabled": True, "health": "ok",
            "notes": None, **extra}


def _page(reg, read_by, **extra):
    return {"id": f"{reg}-page", "regulator_id": reg, "kind": "safety", "sort": 1, "label": f"{reg} safety page",
            "url": f"https://example.test/{reg}", "read_by": read_by, "partial": False, "note": None, **extra}


def _mention(doc, reg, day, seen, **extra):
    return {"document_id": doc, "source_id": f"{reg.lower()}-src", "regulator_id": reg, "regulator_name": reg,
            "country_name": "", "country_code": "", "title": f"Notice {doc}", "lang": "en",
            "link": f"https://example.test/{doc}", "email_id": None, "email_r2_key": None, "date": day,
            "published_date": day, "first_seen_at": seen, "doc_type": "dhpc",
            "terms": [{"text": "levofloxacin", "lang": "en"}], "by_class": False, "is_backfill": False,
            "sections": None, "issue_id": None, "issue_status": None, "decision": None, **extra}


def _reg(rid, country, code, *, runs=0, ok=None, failed=0, unread_page=False, pages=(), sources=(),
         mentions=(), name=None):
    return {"id": rid, "name": name or rid, "country_name": country, "country_code": code,
            "homepage": f"https://{rid.lower()}.example.test/", "hers": bool(pages), "runs": runs,
            "ok": runs - failed if ok is None else ok, "failed": failed, "unread_page": unread_page,
            "pages": list(pages), "sources": list(sources), "mentions": list(mentions)}


REGULATORS = [
    # hers: Austria nothing found, Germany mentioned, Japan not read, Italy a page of hers unread
    _reg("BASG", "Austria", "AT", runs=4, pages=[_page("BASG", ["basg-src"])], sources=[_source("basg-src", "BASG")]),
    _reg("BfArM", "Germany", "DE", runs=3, pages=[_page("BfArM", ["bfarm-src"])],
         sources=[_source("bfarm-src", "BfArM")],
         mentions=[_mention("d-old", "BfArM", "2026-11-02", "2026-11-02T09:00:00Z"),
                   _mention("d-new", "BfArM", "2026-11-05", "2026-11-05T08:10:00Z", issue_id="i-1",
                            issue_status="relevant", by_class=True,
                            terms=[{"text": "Fluorchinolone", "lang": "de"}, {"text": "fluorchinolone", "lang": "nl"}],
                            decision={"to_status": "relevant", "person": "Sama Hassan",
                                      "at": "2026-11-05T10:12:00Z", "comment": "Our product is named"})]),
    _reg("PMDA", "Japan", "JP", runs=0, pages=[_page("PMDA", ["pmda-src"])], sources=[_source("pmda-src", "PMDA")]),
    _reg("AIFA", "Italy", "IT", runs=5, unread_page=True, pages=[_page("AIFA", [])],
         sources=[_source("aifa-src", "AIFA")]),
    # other authorities: Australia not read, Canada failed reads, Brazil nothing found
    _reg("TGA", "Australia", "AU", runs=0, sources=[_source("tga-src", "TGA")]),
    _reg("HC", "Canada", "CA", runs=4, failed=1, sources=[_source("hc-src", "HC")], name="Health Canada"),
    _reg("ANVISA", "Brazil", "BR", runs=2, sources=[_source("anvisa-src", "ANVISA")]),
]


def test_country_answers_rank_as_the_screen():
    hers, others = rw.country_answers(REGULATORS)
    assert [(c["country"], c["answer"]) for c in hers] == [
        ("Germany", "mentioned"), ("Japan", "not_read"), ("Italy", "unread_page"), ("Austria", "fine")]
    assert [(c["country"], c["answer"]) for c in others] == [
        ("Australia", "not_read"), ("Canada", "failed"), ("Brazil", "fine")]
    germany = hers[0]
    assert [m["document_id"] for m in germany["mentions"]] == ["d-new", "d-old"]   # newest first
    texts = {c["country"]: rw.answer_text(c) for c in hers + others}
    assert texts == {
        "Germany": "Mentioned in 2 notices",
        "Japan": "Not read this week — check it by hand",
        "Italy": "A page of hers is not read by the app — check it by hand",
        "Austria": "Nothing found",
        "Australia": "Not read this week — check it by hand",
        "Canada": "1 of 4 reads failed — check it by hand",
        "Brazil": "Nothing found",
    }
    assert rw.reads_text(others[1]) == "Read 4 times this week, 1 failed"
    assert rw.reads_text(hers[1]) == "Not read this week"
    assert rw.summary_line(hers + others) == "Mentioned in 1 of 7 countries · 2 nothing found · 4 to check by hand"


def test_the_answers_are_worded_as_on_the_screen():
    """The report's answers are the screen's (web/src/features/screen/answers.ts), for "this week"."""
    ts = (ROOT / "web/src/features/screen/answers.ts").read_text(encoding="utf-8")
    for words in ("check it by hand", "A page of hers is not read by the app — check it by hand", "Nothing found",
                  "failed — check it by hand", "nothing found · ${check} to check by hand", "Mentioned in "):
        assert words in ts, words
    decisions = (ROOT / "web/src/features/screen/decision.ts").read_text(encoding="utf-8")
    for label in rw.DECISION_LABEL.values():
        assert label in decisions.replace("\\'", "'"), label


def test_answer_of_is_nothing_found_only_when_read_in_full():
    assert rw.answer_of([{}], 0, 0, True) == "mentioned"
    assert rw.answer_of([], 0, 0, False) == "not_read"
    assert rw.answer_of([], 3, 1, True) == "failed"
    assert rw.answer_of([], 3, 0, True) == "unread_page"
    assert rw.answer_of([], 3, 0, False) == "fine"
    assert [a for a in rw.ANSWER_RANK if rw.to_check_by_hand(a)] == ["not_read", "failed", "unread_page"]


def test_page_status_reads_only_through_live_sources():
    sources = {"on": {"id": "on", "enabled": True, "channel": "html"},
               "off": {"id": "off", "enabled": False, "channel": "html"},
               "mail": {"id": "mail", "enabled": True, "channel": "email"}}
    assert rw.page_status(_page("X", ["off"]), sources)["state"] == "unread"
    assert rw.page_status(_page("X", ["gone"]), sources)["state"] == "unread"
    assert rw.page_status(_page("X", ["on"], partial=True), sources)["state"] == "partial"
    by_mail = rw.page_status(_page("X", ["mail"], note="By e-mail subscription: weekly digest"), sources)
    assert by_mail == {"state": "read", "label": "Read by the app, by e-mail subscription", "note": "weekly digest"}


def test_words_are_listed_once_with_their_languages():
    terms = [{"text": "Fluorchinolone", "lang": "de"}, {"text": "fluorchinolone", "lang": "nl"},
             {"text": "levofloxacin", "lang": "en"}, {"text": "Tavanic", "lang": None}]
    assert rw.words_text(terms) == "Fluorchinolone (2 languages), levofloxacin (English), Tavanic"


# ───────────────────────────── gathered from the database ─────────────────────────────

SCREEN = {
    "ingredient": {"id": "00000000-0000-4000-8000-000000000010", "inn_en": "levofloxacin", "atc_code": "J01MA12",
                   "classes": [{"name_en": "Fluoroquinolones"}]},
    "regulators": REGULATORS,
    "label_changes": [_mention("d-spc", "EMA", "2026-11-03", "2026-11-03T07:00:00Z", country_name="European Union",
                               regulator_name="European Medicines Agency", sections=["4.4", "4.8"])],
    "literature": {"papers": 2, "by_name": 1, "by_class": 1, "pubmed": 2, "pmc": 1,
                   "by_query": [{"query": "levofloxacin", "kind": "name", "pubmed": 1, "pmc": 1}]},
}


def _log(sid, reg, country, kind, runs, failed=0, enabled=True, why=None):
    return {"source_id": sid, "regulator_id": reg, "regulator": reg, "country": country, "country_code": "",
            "source_kind": kind, "enabled": enabled, "runs": runs, "ok_runs": runs - failed, "failed_runs": failed,
            "items_seen": runs * 10, "items_new": 0, "items_matched": 0, "last_run": None, "last_failure": why}


# The signal Concerns us opened on notice i-1 (0042), as finding_state() carries it.
SIGNAL = {"id": "sig-1", "ref": "SIG-2026-001", "title": "Rote-Hand-Brief zu Fluorchinolonen", "stage": "validation",
          "priority": None, "outcome": None, "next_step": "validated", "next_due": "2026-12-05", "overdue": False,
          "owner": None, "opened_at": "2026-11-05T10:12:00Z", "opened_by": "Sama Hassan",
          "steps": [{"step": "opened", "from_stage": None, "to_stage": "validation", "priority": None, "outcome": None,
                     "person": "Sama Hassan", "at": "2026-11-05T10:12:00Z", "comment": None}]}


class FakeDb:
    """Answers each query the report makes, and keeps every statement to be read back."""

    def __init__(self):
        self.sql: list[str] = []
        self.written: list[dict] = []

    def fetchone(self, sql, params=None):
        self.sql.append(sql)
        if "finding_state(" in sql:
            # The clock of the notices decided this week, as the screen reads it (0041), and the signal the
            # decision opened (0042).
            assert params == {"ids": ["i-1"]}
            return {"f": {"i-1": {"day_zero": "2026-11-05", "due": "2026-11-10", "days_left": -4, "clock": "sent",
                                  "sent": {"id": "ar-1", "on": "2026-11-06", "reference": "EDA/2026/0042",
                                           "person": "Sama Hassan", "note": None},
                                  "signal": SIGNAL}}}
        if "ingredient_readiness(" in sql:
            # How far the ingredient is prepared, as the Ingredients page reads it (0045).
            assert params == {"i": SCREEN["ingredient"]["id"]}
            return {"readiness": READINESS}
        assert "ingredient_screen(" in sql
        assert params == {"f": date(2026, 11, 1), "t": date(2026, 11, 7), "i": SCREEN["ingredient"]["id"]}
        return {"screen": SCREEN}

    def fetchall(self, sql, params=None):
        self.sql.append(sql)
        if "from ingredient where active" in sql:
            return [{"id": SCREEN["ingredient"]["id"], "inn_en": "levofloxacin"}]
        if "ingredient_papers(" in sql:
            return [{"document_id": "p-1", "title": "Tendon rupture after levofloxacin", "lang": "en",
                     "journal": "Drug Saf", "day": date(2026, 11, 4),
                     "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000001/",
                     "pmc_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9900001/", "by_class": False,
                     "is_backfill": False, "first_seen_at": datetime(2026, 11, 4, 6, tzinfo=UTC)},
                    {"document_id": "p-2", "title": "Fluoroquinolones and aortic aneurysm: a case series", "lang": "en",
                     "journal": "", "day": date(2026, 11, 5), "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000002/",
                     "pmc_url": None, "by_class": True, "is_backfill": False,
                     "first_seen_at": datetime(2026, 11, 5, 6, tzinfo=UTC)}]
        if "paper_state(" in sql:
            assert params == {"ids": ["p-1", "p-2"]}
            return [{"state": {
                "p-1": {"issue_id": "i-p1", "issue_status": "not_relevant",
                        "decision": {"to_status": "not_relevant", "person": "Sama Hassan",
                                     "at": "2026-11-05T11:00:00Z", "comment": "Not our product"},
                        "case_report": None, "day_zero": "2026-11-04", "due_serious": "2026-11-19",
                        "due_nonserious": "2027-02-02"},
                "p-2": {"issue_id": "i-p2", "issue_status": "new", "decision": None,
                        "case_report": {"reason": "title"}, "day_zero": "2026-11-05", "due_serious": "2026-11-20",
                        "due_nonserious": "2027-02-03"}}}]
        if "mlm_monitored(" in sql:
            assert params == {"i": SCREEN["ingredient"]["id"]}
            return [{"monitored": False}]
        if "class_term" in sql:
            return [{"query": "fluoroquinolone", "kind": "class"}, {"query": "levofloxacin", "kind": "name"}]
        if "screening_log(" in sql:
            assert params == {"f": date(2026, 11, 1), "t": date(2026, 11, 7)}
            return [_log("basg-src", "BASG", "Austria", "safety", 4),
                    _log("bfarm-src", "BfArM", "Germany", "safety", 3),
                    _log("pmda-src", "PMDA", "Japan", "safety", 0),
                    _log("aifa-src", "AIFA", "Italy", "safety", 5),
                    _log("hc-src", "HC", "Canada", "safety", 4, failed=1, why="HTTP 503 from hc.example.test"),
                    _log("anvisa-src", "ANVISA", "Brazil", "safety", 2),
                    _log("tga-src", "TGA", "Australia", "safety", 0),
                    _log("ema-spc", "EMA", "European Union", "spc", 7),
                    _log("ncbi", "NCBI", "International", "literature", 7)]
        if "new_items(" in sql:
            assert params == {"a": datetime(2026, 10, 31, 22, tzinfo=UTC), "b": datetime(2026, 11, 7, 22, tzinfo=UTC)}
            return [{"document_id": "d-new", "source_id": "bfarm-src", "regulator_id": "BfArM",
                     "regulator_name": "BfArM", "country_name": "Germany", "source_kind": "safety",
                     "title_orig": "Rote-Hand-Brief zu Fluorchinolonen", "lang": "de",
                     "link": "https://bfarm.example.test/rhb", "published_date": date(2026, 11, 5),
                     "first_seen_at": datetime(2026, 11, 5, 8, 10, tzinfo=UTC), "doc_type": "dhpc", "matched": True,
                     "email_id": None, "email_r2_key": None},
                    {"document_id": "d-x", "source_id": "basg-src", "regulator_id": "BASG", "regulator_name": "BASG",
                     "country_name": "Austria", "source_kind": "safety", "title_orig": "=HYPERLINK(\"x\")",
                     "lang": "de", "link": "javascript:alert(1)", "published_date": None,
                     "first_seen_at": datetime(2026, 11, 6, 23, 30, tzinfo=UTC), "doc_type": "other",
                     "matched": False, "email_id": None, "email_r2_key": None}]
        if "country_look" in sql:
            return [{"country_name": "Germany", "person": "Sama Hassan",
                     "looked_at": datetime(2026, 11, 5, 10, tzinfo=UTC), "looks": 3}]
        if "from regulator\n" in sql or sql.strip().endswith("from regulator"):
            return [{k: r[k] for k in ("id", "name", "country_name", "country_code", "homepage")}
                    for r in REGULATORS] + [
                {"id": "EMA", "name": "European Medicines Agency", "country_name": "European Union",
                 "country_code": "EU", "homepage": "https://www.ema.europa.eu/"},
                {"id": "NCBI", "name": "NCBI", "country_name": "International", "country_code": None,
                 "homepage": "https://www.ncbi.nlm.nih.gov/"}]
        if "from regulator_page" in sql:
            return [p for r in REGULATORS for p in r["pages"]]
        if "from source" in sql and "regulator_page" not in sql:
            return [s for r in REGULATORS for s in r["sources"]] + [
                _source("ema-spc", "EMA", kind="spc"), _source("ncbi", "NCBI", kind="literature")]
        if "review_event" in sql:
            return [{"created_at": datetime(2026, 11, 5, 10, 12, tzinfo=UTC), "from_status": "new",
                     "to_status": "relevant", "comment": "Our product is named", "person": "Sama Hassan",
                     "title": "Rote-Hand-Brief zu Fluorchinolonen", "issue_id": "i-1"}]
        if "from authority_report" in sql:
            assert "withdrawn_at is null" in sql
            assert params == {"f": date(2026, 11, 1), "t": date(2026, 11, 7)}
            return [{"sent_on": date(2026, 11, 6), "reference": "EDA/2026/0042", "note": None,
                     "person": "Sama Hassan", "title": "Rote-Hand-Brief zu Fluorchinolonen", "issue_id": "i-1"}]
        if "from v_eda_clock" in sql:
            return [{"issue_id": "i-9", "clock": "late"}, {"issue_id": "i-8", "clock": "running"},
                    {"issue_id": "i-7", "clock": "running"}]
        if "from v_signal_table" in sql:
            # the signals still open (0042): two of them, one with its step late
            assert "closed" in sql
            return [{"stage": "validation", "overdue": False}, {"stage": "assessment", "overdue": True}]
        raise AssertionError(f"unexpected query: {sql}")

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.written.append(params)


# ingredient_readiness() (0045) for an ingredient added this week: the class is made, its check of the past is
# running, NCBI has not looked back yet, the label watch has not run, nobody receives its messages.
READINESS = {
    "names": {"languages_with_a_name": 1, "of": 15, "missing": ["de", "fr"]},
    "class": {"atc": True, "classes": 1, "words": 17, "confirmed": False},
    "past_check": {"done": False, "words_due": 18, "job_running": True},
    "ncbi": {"searches": 0, "expected": 4, "look_back_done": False, "last_run": None},
    "label_watch": {"products": 0, "by_source": {"spc-cima": {"country": "Spain", "regulator": "AEMPS", "products": 0,
                                                              "read": False},
                                                 "spc-pmda": {"country": "Japan", "regulator": "PMDA", "products": 0,
                                                              "read": False}},
                    "waiting": ["Japan", "Spain"], "empty": [], "first_snapshot": False, "japan_code": False},
    "eurd": {"found": True, "list_read": True, "frequency": "7 years", "dlp": "2031-12-01",
             "next_submission": "2032-02-29"},
    "ema_mlm": {"monitored": False},
    "telegram": {"people": []},
    "ready": False,
}


def _data():
    db = FakeDb()
    return db, rw.assemble(rw.gather_week(db, NOV1), NOV1, made_at=datetime(2026, 11, 8, 3, 2, tzinfo=UTC))


# ───────────────────────────── readiness: any ingredient she adds is covered (0045) ─────────────────────────────

def test_readiness_is_worded_as_on_the_ingredients_page():
    """One line per ingredient, in her words: Ready, or what is still running or still to come."""
    assert rw.readiness_text(READINESS) == ("Still preparing: check of the past running · NCBI look-back tonight · "
                                            "label watch on Monday (Japan, Spain) · nobody receives its Telegram messages yet")
    fresh = {**READINESS, "class": {"atc": True, "classes": 0, "words": 0, "confirmed": False},
             "past_check": {"done": False, "words_due": 1, "job_running": False},
             "ncbi": {"searches": 2, "expected": 4, "look_back_done": False, "last_run": "2026-11-06T00:40:00Z"}}
    assert rw.readiness_items(fresh)[:3] == ["class words tonight", "check of the past tonight", "NCBI look-back running"]
    done = {**READINESS, "ready": True, "class": {"atc": True, "classes": 1, "words": 17, "confirmed": True},
            "past_check": {"done": True, "words_due": 0, "job_running": False},
            "ncbi": {"searches": 4, "expected": 4, "look_back_done": True, "last_run": "2026-11-06T00:40:00Z"},
            "label_watch": {**READINESS["label_watch"], "products": 2, "waiting": []},
            "telegram": {"people": ["Sama Hassan"]}}
    assert rw.readiness_items(done) == [] and rw.readiness_text(done) == "Ready"
    # a label watch that ran everywhere and found nothing is an answer, not something still running
    none = {**done, "label_watch": {**done["label_watch"], "products": 0, "empty": ["Japan", "Spain"]}}
    assert rw.readiness_items(none) == []
    # no ATC code: no class to wait for; no name at all is said first
    assert rw.readiness_items({**done, "class": {"atc": False, "classes": 0, "words": 0, "confirmed": False}}) == []
    assert rw.readiness_items({**done, "names": {"languages_with_a_name": 0, "of": 15, "missing": []}}) == [
        "no name to look for yet"]
    assert rw.country_list(["France", "Germany", "Japan", "Spain"]) == "4 countries"


def test_readiness_words_are_the_screens():
    """The report's readiness words are the Ingredients page's (web/src/features/ingredients/readiness.ts)."""
    ts = (ROOT / "web/src/features/ingredients/readiness.ts").read_text(encoding="utf-8")
    for words in ("Still preparing: ", "Ready", "no name to look for yet", "class words tonight",
                  "check of the past running", "check of the past tonight", "NCBI look-back running",
                  "NCBI look-back tonight", "label watch on Monday (", "nobody receives its Telegram messages yet",
                  " countries"):
        assert words in ts, words


def test_assemble_carries_each_ingredients_readiness():
    db, data = _data()
    assert any("ingredient_readiness(" in s for s in db.sql)
    assert data["readiness"] == [{"name": "levofloxacin", "ready": False,
                                  "text": rw.readiness_text(READINESS)}]
    assert data["ingredients"][0]["readiness"] == data["readiness"][0]


def test_the_pdf_and_excel_say_how_far_each_ingredient_is():
    _, data = _data()
    html = rw.render_weekly_html(data)
    assert "Each ingredient: ready or still preparing" in html
    assert "label watch on Monday (Japan, Spain)" in html
    # in section 01, before the authorities are read
    assert html.index("Each ingredient: ready or still preparing") < html.index('<span class="n">02</span>')
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    rows = list(wb["Summary"].iter_rows(values_only=True))
    assert ("Readiness: levofloxacin", rw.readiness_text(READINESS)) in [(r[0], r[1]) for r in rows]


def test_clock_cells_say_due_late_and_sent_in_her_words():
    assert rw.clock_cells(None) == {"due": "", "sent": "", "signal": ""}
    assert rw.clock_cells({"clock": "off", "due": "2026-11-10", "sent": None}) == {"due": "", "sent": "", "signal": ""}
    assert rw.clock_cells({"clock": "running", "due": "2026-11-10", "sent": None}) == {
        "due": "10 Nov 2026", "sent": "", "signal": ""}
    assert rw.clock_cells({"clock": "late", "due": "2026-11-03", "sent": None}) == {
        "due": "3 Nov 2026 (late)", "sent": "", "signal": ""}
    assert rw.clock_cells({"clock": "sent", "due": "2026-11-10",
                           "sent": {"on": "2026-11-06", "reference": None}}) == {
        "due": "10 Nov 2026", "sent": "6 Nov 2026", "signal": ""}
    # the signal (0042) is shown whatever the clock says: a closed clock does not close the signal
    assert rw.clock_cells({"clock": "off", "due": "2026-11-10", "sent": None, "signal": SIGNAL})["signal"] == (
        "SIG-2026-001 · Validation · due 5 Dec 2026")


def test_the_signal_cell_names_the_stage_its_due_day_and_the_outcome():
    assert rw.signal_cell(None) == ""
    assert rw.signal_cell(SIGNAL) == "SIG-2026-001 · Validation · due 5 Dec 2026"
    assert rw.signal_cell({**SIGNAL, "stage": "assessment", "priority": "high", "next_due": "2026-11-03",
                           "overdue": True}) == "SIG-2026-001 · Assessment, high priority · due 3 Nov 2026 (late)"
    assert rw.signal_cell({**SIGNAL, "stage": "action", "outcome": "label_update", "next_due": "2026-12-20"}) == (
        "SIG-2026-001 · Action: update our label · due 20 Dec 2026")
    assert rw.signal_cell({**SIGNAL, "stage": "closed", "outcome": "not_validated", "next_due": None}) == (
        "SIG-2026-001 · Closed: not validated")
    assert rw.signal_cell({**SIGNAL, "stage": "closed", "outcome": "refuted", "next_due": None}) == (
        "SIG-2026-001 · Closed: refuted")


def test_gather_never_filters_by_run_trigger():
    db, _ = _data()
    assert db.sql and not any("trigger" in s for s in db.sql)


def test_assemble_answers_every_section():
    _, data = _data()
    summary = dict(data["summary"])
    assert summary["Week (Cairo time)"] == "Sun 1 Nov – Sat 7 Nov 2026"
    assert summary["Made (Cairo)"] == "8 Nov 2026, 05:02"
    assert summary["Reference countries read"] == "3 of 4"        # Japan was not read
    assert summary["Notices naming our ingredients or their class"] == 2
    assert summary["Of them, no decision yet"] == 1
    assert summary["Decisions taken this week"] == 1
    # The five-day clock (0041): what was sent this week, what is due now, and the clock on each decision
    assert summary["Reported to the authority this week"] == 1
    assert summary["Due to the authority"] == "3 (1 late)"
    assert data["decisions"][0]["due"] == "10 Nov 2026"
    assert data["decisions"][0]["sent"] == "6 Nov 2026 · EDA/2026/0042"
    assert data["sent"][0]["reference"] == "EDA/2026/0042"
    # The signal steps (0042): the signal on each Concerns us, and how many are open
    assert data["decisions"][0]["signal"] == "SIG-2026-001 · Validation · due 5 Dec 2026"
    assert summary["Signals open"] == "2 (1 step late)"
    # 2. Authorities read: hers first, then the others; label watch and literature apart
    a = data["authorities"]
    assert [r["country"] for r in a["hers"]] == ["Austria", "Germany", "Italy", "Japan"]
    assert [r["country"] for r in a["others"]] == ["Australia", "Brazil", "Canada"]
    assert a["label_watch"]["runs"] == 7 and a["literature"]["runs"] == 7
    # 3. The ingredient, answered as the screen answers
    lev = data["ingredients"][0]
    germany = next(c for c in lev["countries"] if c["country"] == "Germany")
    newest = germany["mentions"][0]
    assert newest["decision"] == "Concerns us"
    assert (newest["decided_by"], newest["decided_at"], newest["reason"]) == (
        "Sama Hassan", "5 Nov 2026, 12:12", "Our product is named")
    assert newest["words"] == "Fluorchinolone (2 languages)" and newest["by_class"]
    assert newest["signal"] == "SIG-2026-001 · Validation · due 5 Dec 2026"
    assert germany["mentions"][1]["decision"] == "No decision yet"
    assert germany["mentions"][1]["signal"] == ""
    assert lev["label_changes"][0]["sections"] == "4.4, 4.8"
    # 4. NCBI: the name first, then the class words; a search with no paper counts 0
    assert lev["literature"]["searches"] == [
        {"query": "levofloxacin", "kind": "name", "pubmed": 1, "pmc": 1},
        {"query": "fluoroquinolone", "kind": "class word", "pubmed": 0, "pmc": 0}]
    # possible case reports first, with day zero, the two dates and the decision on the paper
    assert [(p["pubmed_id"], p["pmc_id"]) for p in lev["literature"]["list"]] == [
        ("41000002", ""), ("41000001", "PMC9900001")]
    case, other = lev["literature"]["list"]
    assert case["case_report"] and case["case_reason"] == "its title says so"
    assert (case["day_zero"], case["due_serious"], case["due_nonserious"]) == (
        "5 Nov 2026", "20 Nov 2026", "3 Feb 2027")
    assert case["decision"] == "No decision yet" and case["awaiting"]
    assert not other["case_report"] and other["decision"] == "Doesn't concern us"
    assert (other["decided_by"], other["decided_at"], other["reason"]) == (
        "Sama Hassan", "5 Nov 2026, 13:00", "Not our product")
    assert lev["literature"]["case_reports"] == 1
    assert lev["literature"]["mlm"] == "Not monitored by EMA: cases in the literature are ours to report"
    assert summary["Possible case reports in the literature"] == 1
    assert summary["Case reports with no decision yet"] == 1
    # 5. Everything new, with who looked; a link that is not a web address is never offered
    new = {n["country"]: n for n in data["new"]}
    assert new["Germany"]["looks"] == [{"person": "Sama Hassan", "at": "5 Nov 2026, 12:00", "looks": 3}]
    assert new["Austria"]["items"][0]["link"] is None
    assert new["Austria"]["items"][0]["day"] == "Found 7 Nov 2026"        # 23:30 UTC is the next day in Cairo
    # 6. To check by hand
    ch = data["check"]
    assert [p["country"] for p in ch["pages"]] == ["Italy"]
    assert [(r["country"], r["failed"], r["why"]) for r in ch["failed"]] == [
        ("Canada", 1, "HTTP 503 from hc.example.test")]
    assert [r["country"] for r in ch["unread"]] == ["Australia", "Japan"]


def test_the_pdf_page_has_six_sections_and_her_words():
    _, data = _data()
    html = rw.render_weekly_html(data)
    heads = re.findall(r'<h2><span class="n">(\d\d)</span>([^<]+)</h2>', html)
    assert heads == [("01", "Summary"), ("02", "Authorities read"), ("03", "Our ingredients by country"),
                     ("04", "NCBI literature"), ("05", "Everything new, per authority"), ("06", "To check by hand")]
    assert html.count('<section class="part">') == 5      # sections 02 to 06 each open a new page
    for words in ("Concerns us", "No decision yet", "Sama Hassan", "Mentioned in 2 notices",
                  "Not read this week — check it by hand", "Looked at by Sama Hassan, 5 Nov 2026, 12:00",
                  "HTTP 503 from hc.example.test", "Sections changed: 4.4, 4.8", "Sun 1 Nov – Sat 7 Nov 2026",
                  "1 possible case report", "Possible case report", "Day zero 5 Nov 2026 · 15 days 20 Nov 2026 · "
                  "90 days 3 Feb 2027", "Not monitored by EMA", "Not our product",
                  "SIG-2026-001 · Validation · due 5 Dec 2026", "Signals open"):
        assert words in html, words
    assert html.count("SIG-2026-001") == 2, "once in the decisions table, once on the notice"
    # the case report is listed before the other paper
    assert html.index("Fluoroquinolones and aortic aneurysm") < html.index("Tendon rupture after levofloxacin")
    assert 'href="https://pubmed.ncbi.nlm.nih.gov/41000001/"' in html
    assert "javascript:" not in html
    assert report.CREDIT in html and html.count(copyright_line()) == 1


def test_the_excel_file_has_a_sheet_per_section_and_her_words():
    _, data = _data()
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    assert wb.sheetnames == list(rw.SHEETS)
    for ws in wb.worksheets:
        assert "Sato Pharma" in (ws.oddFooter.left.text or ""), ws.title
    rows = list(wb["Ingredients by country"].iter_rows(values_only=True))
    germany = [r for r in rows if r[2] == "Germany"]
    assert [r[14] for r in germany] == ["Concerns us", "No decision yet"]
    link = next(c for c in wb["NCBI papers"]["E"] if c.value == "https://pubmed.ncbi.nlm.nih.gov/41000001/")
    assert link.hyperlink.target == link.value
    papers = list(wb["NCBI papers"].iter_rows(values_only=True))
    assert papers[0][8:] == ("Possible case report", "Day zero", "15 days", "90 days", "Decision", "Decided by",
                             "Decided (Cairo)", "Reason")
    assert papers[1][2].startswith("Fluoroquinolones") and papers[1][8:12] == (
        "yes, its title says so", "5 Nov 2026", "20 Nov 2026", "3 Feb 2027")
    # an empty cell reads back as None
    assert tuple(x or "" for x in papers[2][8:]) == (
        "", "", "", "", "Doesn't concern us", "Sama Hassan", "5 Nov 2026, 13:00", "Not our product")
    new = list(wb["Everything new"].iter_rows(values_only=True))
    austria = next(r for r in new if r[1] == "Austria")
    assert austria[4] == '=HYPERLINK("x")' and not austria[6]       # a title is text; no javascript: link
    title = next(c for c in wb["Everything new"]["E"] if c.value == '=HYPERLINK("x")')
    assert title.data_type == "s"
    decisions = list(wb["Decisions"].iter_rows(values_only=True))
    assert decisions[0][6:9] == ("Due", "Sent", "Signal")
    assert decisions[1][2:5] == ("Concerns us", "No decision yet", "Sama Hassan")
    assert decisions[1][6:9] == ("10 Nov 2026", "6 Nov 2026 · EDA/2026/0042", "SIG-2026-001 · Validation · due 5 Dec 2026")
    summary = list(wb["Summary"].iter_rows(values_only=True))
    assert ("Signals open", "2 (1 step late)") in [tuple(r[:2]) for r in summary]


def test_make_weekly_report_archives_records_and_never_overwrites(tmp_path, monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("GIT_SHA", "abc123")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "PHAROS-satopharma/safety")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    printed = []
    monkeypatch.setattr(rw, "build_pdf", lambda html, footer: printed.append(footer) or b"%PDF-1.7 weekly")
    db = FakeDb()
    out = rw.make_weekly_report(db, MemoryStore(), NOV1, dry_run=True)
    assert out["week"] == "2026-11-01"
    row = db.written[-1]
    assert row["s"] == date(2026, 11, 1) and row["e"] == date(2026, 11, 7)
    assert row["pk"] == "reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01.pdf"
    assert row["xk"] == "reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01.xlsx"
    assert row["g"] == "abc123" and row["r"] == "https://github.com/PHAROS-satopharma/safety/actions/runs/42"
    assert "insert into weekly_report" in db.sql[-1] and "on conflict (week_start)" in db.sql[-1]
    assert (tmp_path / "out" / "PHAROS-weekly-2026-11-01.pdf").read_bytes() == b"%PDF-1.7 weekly"
    assert (tmp_path / "out" / "PHAROS-weekly-2026-11-01.xlsx").exists()
    assert "PHAROS · Weekly report · 1 Nov – 7 Nov 2026" in printed[0]
    # made again: stored beside the first, never over it
    rw.make_weekly_report(db, MemoryStore(), NOV1, dry_run=True)
    assert db.written[-1]["pk"] == "reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01-r2.pdf"
    assert (tmp_path / "archive" / "reports/weekly/2026-11-01/PHAROS-weekly-2026-11-01.pdf").exists()


# ───────────────────────────── a real PDF ─────────────────────────────

def _poppler() -> bool:
    exe = shutil.which("pdftotext")
    if not exe:
        return False
    proc = subprocess.run([exe, "-v"], capture_output=True, check=False)
    return b"poppler" in (proc.stdout + proc.stderr).lower()


def _unavailable(reason: str):
    # CI sets REPORT_PDF=true when the report changed: there a missing tool fails the test, it never skips.
    if os.environ.get("REPORT_PDF") == "true":
        pytest.fail(reason)
    pytest.skip(reason)


def test_every_weekly_pdf_page_prints_the_footer(tmp_path):
    if not _poppler():
        _unavailable("needs poppler's pdftotext")
    try:
        from playwright.sync_api import Error as PlaywrightError
    except ImportError:
        _unavailable("needs Playwright (pip install -r collectors/requirements.txt)")
    _, data = _data()
    germany = next(n for n in data["new"] if n["country"] == "Germany")
    germany["items"] = germany["items"] * 200          # more than ten pages
    html = re.sub(r"<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>", "", rw.render_weekly_html(data))
    try:
        pdf = report.build_pdf(html, render_footer(NOV1))
    except PlaywrightError as e:
        _unavailable(f"needs Chromium (python -m playwright install chromium): {e}")
    path = tmp_path / "weekly.pdf"
    path.write_bytes(pdf)
    text = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True,
                          check=True).stdout.decode("utf-8")
    pages = [p for p in text.split("\f") if p.strip()]
    total = len(pages)
    assert total >= 10
    for n, page_text in enumerate(pages, start=1):
        foot = " ".join(page_text.strip().splitlines()[-1].split())
        assert foot.startswith("PHAROS · Weekly report · 1 Nov – 7 Nov 2026 "), f"page {n}: {foot}"
        assert "…" not in foot, f"page {n}: the footer is cut: {foot}"
        assert foot.endswith(f"Page {n} of {total}"), f"page {n}: {foot}"
    # sections 02 to 06 each start a page
    starts = [n for n, p in enumerate(pages, start=1) for head in ("02 Authorities read", "03 Our ingredients",
              "04 NCBI literature", "05 Everything new", "06 To check by hand")
              if " ".join(p.split()).startswith(head)]
    assert len(starts) == 5
