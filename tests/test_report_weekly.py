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
    "literature": {"papers": 2, "by_name": 1, "by_class": 1, "pubmed": 2, "pmc": 1, "europepmc": 1,
                   "by_query": [{"query": "levofloxacin", "kind": "name", "pubmed": 1, "pmc": 1, "europepmc": 1}]},
}


# What label_changes() (0043) answers for the week: the reference product first, then newest first.
OUR_LABEL = {"id": "l-1", "product_name": "Levox 500 mg", "version": "Leaflet 2025", "lang": "en",
             "uploaded_at": "2026-10-20T08:00:00+00:00", "uploaded_by": "Sama Hassan"}
GAP_SECTION = {"section": "4.4", "our_section": "4.4", "our_text": True, "covered": 2, "partly": 1, "missing": 1,
               "added": [{"sentence": "Cases of acute kidney injury have been reported.", "status": "covered",
                          "score": 1.0, "closest": "Cases of acute kidney injury have been reported."}]}
LABEL_CHANGES = [
    {"change_id": "c-1", "detected_at": "2026-11-03T07:00:00+00:00", "detected_day": "2026-11-03",
     "label_date": "2026-10-01", "previous_label_date": "2026-06-01",
     "product": {"id": "p-1", "name": "Tavanic 500 mg", "mah": "Sanofi", "country_code": "EU",
                 "country_name": "European Union", "source_id": "ema-spc", "regulator_id": "EMA",
                 "regulator_name": "European Medicines Agency", "url": "https://example.test/d-spc",
                 "is_reference": True},
     "lang": "en", "link": "https://example.test/d-spc", "document_id": "d-spc", "title": "Tavanic 500 mg — 4.4, 4.8",
     "sections": ["4.4", "4.8"], "diff": [],
     "gap": {"lang_match": True, "our_lang": "en", "their_lang": "en", "covered": 2, "partly": 1, "missing": 1,
             "sections": [GAP_SECTION]},
     "gap_at": "2026-11-03T07:00:05+00:00", "our_label": OUR_LABEL,
     "issue_id": "i-2", "issue_status": "relevant", "is_backfill": False,
     "decision": {"to_status": "relevant", "person": "Sama Hassan", "at": "2026-11-05T10:12:00Z",
                  "comment": "Section 4.4 is not in ours"}},
    {"change_id": "c-2", "detected_at": "2026-11-05T22:30:00+00:00", "detected_day": "2026-11-06",
     "label_date": None, "previous_label_date": None,
     "product": {"id": "p-2", "name": "Lévofloxacine Biogaran 500 mg", "mah": "Biogaran", "country_code": "FR",
                 "country_name": "France", "source_id": "bdpm-spc", "regulator_id": "ANSM", "regulator_name": "ANSM",
                 "url": None, "is_reference": False},
     "lang": "fr", "link": "https://example.test/bdpm", "document_id": None, "title": "Lévofloxacine Biogaran 500 mg — 4.8",
     "sections": ["4.8"], "diff": [],
     "gap": {"lang_match": False, "our_lang": "en", "their_lang": "fr", "covered": 0, "partly": 0, "missing": 0,
             "sections": []},
     "gap_at": "2026-11-05T22:30:05+00:00", "our_label": OUR_LABEL,
     "issue_id": None, "issue_status": None, "is_backfill": False, "decision": None},
    {"change_id": "c-3", "detected_at": "2026-11-04T07:00:00+00:00", "detected_day": "2026-11-04",
     "label_date": "2026-10-15", "previous_label_date": None,
     "product": {"id": "p-3", "name": "Levofloxacin Teva 500 mg", "mah": "Teva", "country_code": "EU",
                 "country_name": "European Union", "source_id": "ema-spc", "regulator_id": "EMA",
                 "regulator_name": "European Medicines Agency", "url": None, "is_reference": False},
     "lang": "en", "link": "javascript:alert(1)", "document_id": None, "title": "Levofloxacin Teva 500 mg — 10",
     "sections": ["10"], "diff": [], "gap": None, "gap_at": None, "our_label": None,
     "issue_id": None, "issue_status": None, "is_backfill": True, "decision": None},
]


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


def _ref(name, scope, *, by_hand=False, searches=0, found=None, check=None, last=None):
    return {"id": name, "scope": scope, "name": name, "url": f"https://{name.split()[0].lower()}.example.test/",
            "note": None, "by_hand": by_hand, "searched_in": [] if by_hand else ["pubmed"], "journal_like": None,
            "searches": searches, "last_searched": last, "hits": 0, "found": found, "check": check}


NOTHING = {"result": "nothing", "note": None, "checked_at": "2026-11-04T08:00:00Z", "checked_by": "Sama Hassan"}
REFS_ING = [_ref("PubMed (NCBI)", "global", searches=7, found=0, last="2026-11-07T04:00:00Z"),
            _ref("Europe PMC", "global", searches=7, found=1, last="2026-11-07T04:00:00Z"),
            _ref("Medscape", "global", by_hand=True, check=NOTHING),
            _ref("Al-Azhar Medical Journal", "local", by_hand=True),
            # never searched this week (the log starts with 0101), and searched but with a failed read
            _ref("PubMed Central (NCBI)", "global", searches=0, found=0),
            {**_ref("Cochrane Database of Systematic Reviews", "global", searches=7, found=0), "failed_reads": 2},
            # its class words were searched, its own name was not
            {**_ref("Europe PMC (class words only)", "global", searches=3, found=0), "name_searches": 0}]
REFS_WEEK = [{**r, "found": None} for r in REFS_ING]


class FakeDb:
    """Answers each query the report makes, and keeps every statement to be read back."""

    def __init__(self, period=None):
        self.sql: list[str] = []
        self.written: list[dict] = []
        # The days and the instants the report must ask for: the week of 1 Nov, or the day it is given.
        period = period or NOV1
        self.days = {"f": period.start, "t": period.end}
        a, b = period.bounds_utc()
        self.bounds = {"a": a, "b": b}

    def fetchone(self, sql, params=None):
        self.sql.append(sql)
        if "finding_state(" in sql:
            # The clock of the notices decided this week, as the screen reads it (0041), and the signal the
            # decision opened (0042).
            # i-1 was decided this week; i-2 (the reference product's label change) concerns us from before.
            assert params == {"ids": ["i-1", "i-2"]}
            return {"f": {"i-1": {"day_zero": "2026-11-05", "due": "2026-11-10", "days_left": -4, "clock": "sent",
                                  "sent": {"id": "ar-1", "on": "2026-11-06", "reference": "EDA/2026/0042",
                                           "person": "Sama Hassan", "note": None},
                                  "signal": SIGNAL},
                          "i-2": {"day_zero": "2026-10-20", "due": "2026-10-25", "days_left": -12, "clock": "late",
                                  "sent": None,
                                  "signal": {**SIGNAL, "id": "sig-2", "ref": "SIG-2026-002", "stage": "assessment",
                                             "priority": "high", "next_step": "assessed",
                                             "next_due": "2026-11-03", "overdue": True}}}}
        if "ingredient_readiness(" in sql:
            # How far the ingredient is prepared, as the Ingredients page reads it (0045).
            assert params == {"i": SCREEN["ingredient"]["id"]}
            return {"readiness": READINESS}
        if "literature_refs_week(null" in sql:
            # Her literature references for the week, every search counted (0101).
            assert params == self.days
            return {"refs": REFS_WEEK}
        assert params == {**self.days, "i": SCREEN["ingredient"]["id"]}
        if "literature_refs_week(" in sql:
            # ... and for the ingredient, with what each found.
            return {"refs": REFS_ING}
        if "label_changes(" in sql:
            # Our label under "Label changes" (0043): the changes of the week with the gap against our label.
            return {"changes": LABEL_CHANGES}
        assert "ingredient_screen(" in sql
        return {"screen": SCREEN}

    def fetchall(self, sql, params=None):
        self.sql.append(sql)
        if "from ingredient where active" in sql:
            return [{"id": SCREEN["ingredient"]["id"], "inn_en": "levofloxacin"}]
        if "ingredient_papers(" in sql:
            return [{"document_id": "p-1", "title": "Tendon rupture after levofloxacin", "lang": "en",
                     "journal": "Drug Saf", "day": date(2026, 11, 4),
                     "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000001/",
                     "pmc_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9900001/",
                     "europepmc_url": "https://europepmc.org/article/PPR/PPR900001", "preprint": True,
                     "by_class": False,
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
            assert params == self.days
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
            assert params == self.bounds
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
            assert params == self.days
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
    assert rw.readiness_text(READINESS) == ("Still preparing: check of the past running · PubMed look-back waiting · "
                                            "label watch on Monday (Japan, Spain) · nobody receives its Telegram messages yet")
    fresh = {**READINESS, "class": {"atc": True, "classes": 0, "words": 0, "confirmed": False},
             "past_check": {"done": False, "words_due": 1, "job_running": False},
             "ncbi": {"searches": 2, "expected": 4, "look_back_done": False, "last_run": "2026-11-06T00:40:00Z"}}
    assert rw.readiness_items(fresh)[:3] == ["class words waiting", "check of the past waiting", "PubMed look-back running"]
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
    # Europe PMC (0082): waited for only while its watch is switched on
    epmc = {"watched": True, "searches": 0, "expected": 2, "look_back_done": False, "last_run": None}
    assert rw.readiness_items({**done, "europepmc": epmc}) == ["Europe PMC look-back waiting"]
    assert rw.readiness_items({**done, "europepmc": {**epmc, "searches": 1}}) == ["Europe PMC look-back running"]
    assert rw.readiness_items({**done, "europepmc": {**epmc, "watched": False}}) == []
    assert rw.readiness_items({**done, "europepmc": {**epmc, "searches": 2, "look_back_done": True}}) == []
    # 0092: it fills in the background and holds nothing
    assert rw.readiness_items({**done, "europepmc": {**epmc, "holds_ready": False}}) == []


def test_readiness_words_are_the_screens():
    """The report's readiness words are the Ingredients page's (web/src/features/ingredients/readiness.ts)."""
    ts = (ROOT / "web/src/features/ingredients/readiness.ts").read_text(encoding="utf-8")
    for words in ("Still preparing: ", "Ready", "no name to look for yet", "class words waiting",
                  "check of the past running", "check of the past waiting", "PubMed look-back running",
                  "PubMed look-back waiting", "Europe PMC look-back running", "Europe PMC look-back waiting",
                  "label watch on Monday (", "nobody receives its Telegram messages yet",
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
    # under its own heading on the Summary sheet, one row per ingredient
    labels = [r[0] for r in rows]
    assert "Each ingredient: ready or still preparing" in labels
    assert ("levofloxacin", rw.readiness_text(READINESS)) in [(r[0], r[1]) for r in rows]
    assert labels.index("Each ingredient: ready or still preparing") < labels.index("levofloxacin")


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
    # Label changes come from label_changes() (0043): the reference product first, with our label's gap
    assert summary["Label changes"] == 3
    lc = lev["label_changes"]
    assert [m["product"] for m in lc] == ["Tavanic 500 mg", "Lévofloxacine Biogaran 500 mg", "Levofloxacin Teva 500 mg"]
    assert lc[0]["sections"] == "4.4, 4.8" and lc[0]["reference"] and not lc[1]["reference"]
    assert lc[0]["day"] == "Detected 3 Nov 2026" and lc[0]["label_day"] == "1 Oct 2026"
    assert lc[0]["mah"] == "Sanofi" and lc[0]["country"] == "European Union"
    assert lc[0]["authority"] == "European Medicines Agency" and lc[0]["doc_type"] == "Label change"
    assert lc[0]["gap_summary"] == "Our label: 2 covered, 1 partly, 1 missing"
    assert lc[0]["our_label"] == "Levox 500 mg, Leaflet 2025"
    assert (lc[0]["decision"], lc[0]["decided_by"], lc[0]["decided_at"], lc[0]["reason"]) == (
        "Concerns us", "Sama Hassan", "5 Nov 2026, 12:12", "Section 4.4 is not in ours")
    assert lc[1]["day"] == "Detected 6 Nov 2026" and lc[1]["label_day"] == ""      # 22:30 UTC is the next day in Cairo
    assert lc[1]["gap_summary"] == "Not compared: different language"
    assert lc[1]["decision"] == "No decision yet" and lc[1]["awaiting"]
    assert lc[2]["gap_summary"] == "No label of ours uploaded" and lc[2]["history"]
    assert lc[2]["link"] is None and lc[2]["our_label"] == ""
    assert rw.gap_summary(None, OUR_LABEL) == "Not compared yet"
    assert rw.gap_summary({"lang_match": True, "covered": 0, "partly": 0, "missing": 0, "sections": []},
                          OUR_LABEL) == "Our label: 0 covered, 0 partly, 0 missing"
    # the label change that concerns us shows the signal its decision opened (0042), even if decided before the week
    assert lc[0]["signal"] == "SIG-2026-002 · Assessment, high priority · due 3 Nov 2026 (late)"
    assert lc[1]["signal"] == "" and lc[2]["signal"] == ""
    # 4. Literature: the name first, then the class words; a search with no paper counts 0
    assert lev["literature"]["searches"] == [
        {"query": "levofloxacin", "kind": "name", "pubmed": 1, "pmc": 1, "europepmc": 1},
        {"query": "fluoroquinolone", "kind": "class word", "pubmed": 0, "pmc": 0, "europepmc": 0}]
    # possible case reports first, with day zero, the two dates and the decision on the paper
    assert [(p["pubmed_id"], p["pmc_id"]) for p in lev["literature"]["list"]] == [
        ("41000002", ""), ("41000001", "PMC9900001")]
    # Europe PMC's page and the preprint flag reach the report; a paper without them has neither
    assert [(p["europepmc_id"], p["preprint"]) for p in lev["literature"]["list"]] == [
        ("", False), ("PPR900001", True)]
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
                     ("04", "Literature"), ("05", "Everything new, per authority"), ("06", "To check by hand")]
    assert html.count('<section class="part">') == 5      # sections 02 to 06 each open a new page
    for words in ("Concerns us", "No decision yet", "Sama Hassan", "Mentioned in 2 notices",
                  "Not read this week — check it by hand", "Looked at by Sama Hassan, 5 Nov 2026, 12:00",
                  "HTTP 503 from hc.example.test", "Sections changed: 4.4, 4.8", "Sun 1 Nov – Sat 7 Nov 2026",
                  "Detected 3 Nov 2026", "Label dated 1 Oct 2026", "Tavanic 500 mg", "Sanofi", "Reference product",
                  "Our label: 2 covered, 1 partly, 1 missing", "Not compared: different language",
                  "No label of ours uploaded", "Levox 500 mg, Leaflet 2025",
                  "1 possible case report", "Possible case report", "Day zero 5 Nov 2026 · 15 days 20 Nov 2026 · "
                  "90 days 3 Feb 2027", "Not monitored by EMA", "Not our product",
                  "SIG-2026-001 · Validation · due 5 Dec 2026", "Signals open"):
        assert words in html, words
    assert html.count("SIG-2026-001") == 2, "once in the decisions table, once on the notice"
    # the case report is listed before the other paper
    assert html.index("Fluoroquinolones and aortic aneurysm") < html.index("Tendon rupture after levofloxacin")
    assert 'href="https://pubmed.ncbi.nlm.nih.gov/41000001/"' in html
    assert '<a href="https://europepmc.org/article/PPR/PPR900001">PPR900001</a>' in html
    assert '<span class="tag">preprint</span>' in html and "Europe PMC" in html
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
    labels = [r for r in rows if r[1] == "Label changes"]
    assert [r[2] for r in labels] == ["European Union", "France", "European Union"]
    assert labels[0][3] == "Our label: 2 covered, 1 partly, 1 missing" and labels[0][4] == "Levox 500 mg, Leaflet 2025"
    assert labels[0][5] == "Detected 3 Nov 2026" and labels[0][6] == "Tavanic 500 mg — 4.4, 4.8"
    assert labels[0][11] == "Sections changed: 4.4, 4.8 · Label dated 1 Oct 2026 · Sanofi · Reference product"
    assert labels[1][3] == "Not compared: different language" and labels[2][3] == "No label of ours uploaded"
    assert not labels[2][8]                                              # no javascript: link
    link = next(c for c in wb["Literature papers"]["E"] if c.value == "https://pubmed.ncbi.nlm.nih.gov/41000001/")
    assert link.hyperlink.target == link.value
    papers = list(wb["Literature papers"].iter_rows(values_only=True))
    assert papers[0][6:8] == ("Europe PMC", "Preprint")
    assert papers[2][6:8] == ("https://europepmc.org/article/PPR/PPR900001", "yes")
    assert papers[0][10:] == ("Possible case report", "Day zero", "15 days", "90 days", "Decision", "Decided by",
                             "Decided (Cairo)", "Reason")
    assert papers[1][2].startswith("Fluoroquinolones") and papers[1][10:14] == (
        "yes, its title says so", "5 Nov 2026", "20 Nov 2026", "3 Feb 2027")
    # an empty cell reads back as None
    assert tuple(x or "" for x in papers[2][10:]) == (
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


def test_every_literature_reference_has_its_negative_result_in_words():
    # Dr Sama, 8 Nov 2026 (0101): each Global and Local reference, how it was screened, and "Nothing found".
    _, data = _data()
    refs = {r["name"]: r for r in data["ingredients"][0]["literature"]["refs"]}
    assert refs["PubMed (NCBI)"]["screened"] == "Searched by the app — 7 searches this week, last 7 Nov 2026, 06:00"
    assert refs["PubMed (NCBI)"]["found"] == "Nothing found" and refs["Europe PMC"]["found"] == "1 paper"
    assert refs["Medscape"]["screened"] == "Checked by hand — Sama Hassan, 4 Nov 2026, 10:00"
    assert refs["Medscape"]["found"] == "Nothing found"
    assert refs["Al-Azhar Medical Journal"]["found"] == "Not checked" and refs["Al-Azhar Medical Journal"]["gap"]
    assert refs["Al-Azhar Medical Journal"]["scope"] == "Local"
    # "Nothing found" only when the name was searched and no read failed (risk review of PR 223)
    assert refs["PubMed Central (NCBI)"]["screened"] == "Not searched by the app this week"
    assert refs["PubMed Central (NCBI)"]["found"] == "Not searched — check by hand" and refs["PubMed Central (NCBI)"]["gap"]
    cochrane = refs["Cochrane Database of Systematic Reviews"]
    assert cochrane["screened"].endswith("; 2 reads failed")
    assert cochrane["found"] == "Not fully searched — check by hand" and cochrane["gap"]
    assert refs["Europe PMC (class words only)"]["found"] == "Not searched — check by hand"
    week = {r["name"]: r for r in data["authorities"]["literature_refs"]}
    assert week["PubMed (NCBI)"]["found"] == "" and not week["PubMed (NCBI)"]["gap"]

    html = rw.render_weekly_html(data)
    assert "Literature references, Global and Local" in html
    assert "<strong>Nothing found</strong>" in html
    assert "Checked by hand — not checked this week" in html
    rows = list(load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))["Literature references"].iter_rows(values_only=True))
    assert rows[0] == ("Ingredient", "List", "Reference", "Link", "Screened", "Found")
    assert ("levofloxacin", "Global", "PubMed (NCBI)") == rows[1][:3] and rows[1][5] == "Nothing found"
    assert rows[4][1:3] == ("Local", "Al-Azhar Medical Journal") and rows[4][5] == "Not checked"


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


# ───────────────────────────── the daily report (owner, 6 Nov 2026) ─────────────────────────────

NOV5 = rw.Day(date(2026, 11, 5))


def test_a_day_runs_midnight_to_midnight_in_cairo_time():
    assert NOV5.end == NOV5.start == date(2026, 11, 5)
    assert NOV5.label == "Thu 5 Nov 2026" and NOV5.slug == "2026-11-05"
    assert NOV5.footer == "Daily report · Thu 5 Nov 2026"
    assert len(NOV5.footer) <= len(report.Month(date(2026, 9, 1)).footer)
    # winter (UTC+2) and summer (UTC+3)
    assert NOV5.bounds_utc() == (datetime(2026, 11, 4, 22, tzinfo=UTC), datetime(2026, 11, 5, 22, tzinfo=UTC))
    assert rw.Day(date(2026, 8, 5)).bounds_utc() == (datetime(2026, 8, 4, 21, tzinfo=UTC),
                                                    datetime(2026, 8, 5, 21, tzinfo=UTC))


def test_the_daily_report_is_of_the_last_day_that_ended_in_cairo():
    # Friday 6 Nov 2026 at 07:00 Cairo, when the schedule makes it
    assert rw.yesterday(datetime(2026, 11, 6, 5, tzinfo=UTC)) == NOV5
    # 00:30 Cairo on Friday is still Thursday in UTC
    assert rw.yesterday(datetime(2026, 11, 5, 22, 30, tzinfo=UTC)) == NOV5
    # 23:59 Cairo on Thursday: Thursday has not ended yet
    assert rw.yesterday(datetime(2026, 11, 5, 21, 59, tzinfo=UTC)).start == date(2026, 11, 4)


def test_the_command_refuses_a_wrong_day_before_it_connects(capsys):
    with pytest.raises(SystemExit) as e:
        report.main(["--day", "2026-11-31"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        report.main(["--daily", "--week", "2026-11-01"])
    assert e.value.code == 2


def test_the_daily_report_is_the_weekly_one_read_for_one_day():
    db = FakeDb(NOV5)
    data = rw.assemble(rw.gather_week(db, NOV5), NOV5, made_at=datetime(2026, 11, 6, 5, 2, tzinfo=UTC))
    summary = dict(data["summary"])
    assert summary["Report"] == "PHAROS — Daily screening report"
    assert summary["Day (Cairo time)"] == "Thu 5 Nov 2026"
    assert "Week (Cairo time)" not in summary
    assert "Decisions taken on the day" in summary and "Sources not read on the day" in summary
    html = rw.render_weekly_html(data)
    assert "<title>PHAROS — Daily screening report · Thu 5 Nov 2026</title>" in html
    assert "Daily screening report" in html and "Not read on the day — check it by hand" in html
    assert "this week" not in html and "Weekly" not in html
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    assert wb.sheetnames == list(rw.SHEETS)
    words = " ".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v)
    assert "this week" not in words and "Daily screening report" in words


def test_make_daily_report_archives_and_records_the_day(tmp_path, monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "out"))
    printed = []
    monkeypatch.setattr(rw, "build_pdf", lambda html, footer: printed.append(footer) or b"%PDF-1.7 daily")
    db = FakeDb(NOV5)
    out = rw.make_weekly_report(db, MemoryStore(), NOV5, dry_run=True)
    assert out["day"] == "2026-11-05"
    row = db.written[-1]
    assert row["s"] == date(2026, 11, 5)
    assert row["pk"] == "reports/daily/2026-11-05/PHAROS-daily-2026-11-05.pdf"
    assert row["xk"] == "reports/daily/2026-11-05/PHAROS-daily-2026-11-05.xlsx"
    assert "insert into daily_report" in db.sql[-1] and "on conflict (day)" in db.sql[-1]
    assert (tmp_path / "out" / "PHAROS-daily-2026-11-05.pdf").read_bytes() == b"%PDF-1.7 daily"
    assert "PHAROS · Daily report · Thu 5 Nov 2026" in printed[0]
    rw.make_weekly_report(db, MemoryStore(), NOV5, dry_run=True)
    assert db.written[-1]["pk"] == "reports/daily/2026-11-05/PHAROS-daily-2026-11-05-r2.pdf"


def _unread(period, **changes):
    """The countries listed as "not read" when the sources named in ``changes`` are changed as given."""
    raw = rw.gather_week(FakeDb(period), period)
    raw["sources"] = [{**src, **changes.get(src["id"], {})} for src in raw["sources"]]
    data = rw.assemble(raw, period, made_at=datetime(2026, 11, 8, 3, 2, tzinfo=UTC))
    return [r["country"] for r in data["check"]["unread"]], dict(data["summary"])


def test_a_source_added_after_the_period_is_never_listed_as_not_read():
    """The 5 Nov daily report listed EMA's news page, Swissmedic's updates, Europe PMC and the FDA and Health Canada
    e-mails as "not read on the day": they were added on 6 Nov."""
    assert _unread(NOV1)[0] == ["Australia", "Japan"]
    later = {"created_at": datetime(2026, 11, 8, 9, tzinfo=UTC)}            # after Sat 7 Nov, Cairo midnight
    assert _unread(NOV1, **{"pmda-src": later})[0] == ["Australia"]
    during = {"created_at": "2026-11-03T09:00:00+00:00"}                     # added during the week: still due
    assert _unread(NOV1, **{"pmda-src": during})[0] == ["Australia", "Japan"]
    assert _unread(NOV5, **{"pmda-src": {"created_at": "2026-11-05T22:30:00+00:00"}})[0] == ["Australia"]


def test_a_weekly_source_is_not_due_every_day():
    weekly = {"schedule": "weekly"}
    assert _unread(NOV5, **{"tga-src": weekly})[0] == ["Japan"]
    assert _unread(NOV5, **{"tga-src": {"schedule": "daily"}})[0] == ["Australia", "Japan"]
    # the weekly report still lists it
    assert _unread(NOV1, **{"tga-src": weekly})[0] == ["Australia", "Japan"]


def test_the_report_says_which_period_it_covers():
    for period, span in ((NOV1, "Sunday to Saturday, Cairo time"), (NOV5, "Midnight to midnight, Cairo time")):
        html = rw.render_weekly_html(rw.assemble(rw.gather_week(FakeDb(period), period), period))
        assert f'<p class="scope">{span}. Every source read in its own language' in html
    assert "Sunday to Saturday" not in rw.render_weekly_html(rw.assemble(rw.gather_week(FakeDb(NOV5), NOV5), NOV5))
    assert "Papers in PubMed, PubMed Central and Europe PMC" in _unread(NOV1)[1]


def test_the_summary_groups_carry_every_figure_once():
    for period in (NOV1, NOV5):
        data = rw.assemble(rw.gather_week(FakeDb(period), period), period)
        grouped = [k for _, rows in data["summary_groups"] for k, _ in rows]
        head = {"Report", period.period_head, "Made (Cairo)"}
        assert sorted(grouped) == sorted(k for k, _ in data["summary"] if k not in head)
        assert [h for h, _ in data["summary_groups"]] == [
            "Screening", "What concerns our ingredients", "Literature", "Decisions and the five-day clock",
            "To check by hand"]


def test_the_polished_files():
    data = rw.assemble(rw.gather_week(FakeDb(NOV5), NOV5), NOV5, made_at=datetime(2026, 11, 6, 5, 2, tzinfo=UTC))
    html = rw.render_weekly_html(data)
    assert "<h1>Daily screening report</h1>" in html and '<p class="period">Thu 5 Nov 2026</p>' in html
    assert "Made 6 Nov 2026, 07:02 (Cairo)" in html
    assert html.count('<div class="summary-grid">') == 1
    # a country with nothing new is named in one line, never given a block of its own
    quiet = [n["country"] for n in data["new"] if not n["items"]]
    assert quiet and all(f"<h4>{c} · " not in html for c in quiet)
    assert "Nothing new on the day:</strong>" in html
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    for ws in wb.worksheets:
        assert ws.sheet_view.showGridLines is False, ws.title
        assert ws.page_setup.orientation == "landscape" and ws.page_setup.fitToWidth == 1, ws.title
        assert "PHAROS — Daily screening report" in (ws.oddHeader.left.text or ""), ws.title
    assert wb["Decisions"]["A2"].value == "5 Nov 2026, 12:12"              # the fixture's decision
    quiet_day = load_workbook(io.BytesIO(rw.build_weekly_xlsx({**data, "decisions": []})))
    assert quiet_day["Decisions"]["A2"].value == "No decision was taken on the day."
    assert wb["Decisions"].print_title_rows == "$1:$1"           # the header row on every printed page
    summary = [r[0] for r in wb["Summary"].iter_rows(values_only=True)]
    assert "Screening" in summary and "To check by hand" in summary


def test_the_findings_come_first_with_their_links_and_decisions():
    data = rw.assemble(rw.gather_week(FakeDb(NOV1), NOV1), NOV1)
    expected = [(i["name"], m["title"]) for i in data["ingredients"]
                for m in [m for c in i["countries"] for m in c["mentions"]] + i["label_changes"] + i["literature"]["list"]]
    assert expected and [(f["ingredient"], f["title"]) for f in data["findings"]] == expected
    kinds = {f["what"] for f in data["findings"]}
    assert "Notice" in kinds and "Label change" in kinds
    html = rw.render_weekly_html(data)
    assert html.index("What was found about our ingredients") < html.index('<div class="summary-grid">')
    for f in data["findings"]:
        if f["link"]:
            assert f'href="{f["link"]}"' in html
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    assert wb.sheetnames[:2] == ["Summary", "Findings"]
    rows = list(wb["Findings"].iter_rows(min_row=2, values_only=True))
    assert [(r[0], r[5]) for r in rows] == expected
    assert [r[8] for r in rows] == [f["decision"] for f in data["findings"]]


def test_no_finding_is_said_in_words():
    data = rw.assemble(rw.gather_week(FakeDb(NOV1), NOV1), NOV1)
    data["findings"] = []
    assert "Nothing about our ingredients was found this week" in rw.render_weekly_html(data)
    wb = load_workbook(io.BytesIO(rw.build_weekly_xlsx(data)))
    assert wb["Findings"]["A2"].value == "Nothing about our ingredients was found this week."


def test_a_preview_is_never_archived_recorded_or_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(rw, "build_pdf", lambda html, footer: b"%PDF-1.7 preview")
    db = FakeDb(NOV5)
    assert rw.make_weekly_report(db, MemoryStore(), NOV5, preview=True) == {"preview": "PHAROS-daily-2026-11-05"}
    assert db.written == [] and not any("insert into" in q for q in db.sql)
    assert not (tmp_path / "archive").exists()
    assert (tmp_path / "out" / "PHAROS-daily-2026-11-05.pdf").read_bytes() == b"%PDF-1.7 preview"
    assert (tmp_path / "out" / "PHAROS-daily-2026-11-05.xlsx").exists()


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
              "04 Literature", "05 Everything new", "06 To check by hand")
              if " ".join(p.split()).startswith(head)]
    assert len(starts) == 5


def test_the_week_counts_her_label_database_pages():
    # Her database pages (regulator_page, kind 'database') as the Ingredients page counts them (0095): read when a
    # switched-on labels source reading the page completed a run in the week.
    pages = [_page("EMA", ["ema-spc"], id="p1", kind="database"),
             _page("AEMPS", ["spc-cima"], id="p2", kind="database"),      # its reader failed every run
             _page("TGA", [], id="p3", kind="database"),                   # no reader: blocked
             _page("CBG", ["spc-cbg"], id="p4", kind="database"),          # reader switched off
             _page("EMA", ["ema-dhpc"], id="p5")]                          # a safety page, not counted
    sources = [_source("ema-spc", "EMA", kind="spc"), _source("spc-cima", "AEMPS", kind="spc"),
               _source("spc-cbg", "CBG", kind="spc", enabled=False), _source("ema-dhpc", "EMA")]
    log = {"ema-spc": _log("ema-spc", "EMA", "European Union", "spc", 1),
           "spc-cima": _log("spc-cima", "AEMPS", "Spain", "spc", 2, failed=2)}
    d = rw.label_databases(pages, sources, log)
    assert d == {"total": 4, "read": 1, "missed": 1, "not_read": 2}
    assert rw.label_databases_text(d) == (
        "1 of 4 pages · 1 not read this week · 2 not read by the app (reasons on the Sources page)")
    assert rw.label_databases_text({"total": 27, "read": 19, "missed": 0, "not_read": 8}) == (
        "19 of 27 pages · 8 not read by the app (reasons on the Sources page)")
    assert rw.label_databases_text({"total": 0, "read": 0, "missed": 0, "not_read": 0}) == "no database pages listed"


def test_the_weekly_summary_says_how_many_label_databases_were_read():
    _, data = _data()
    assert dict(data["summary"])["Label databases read"] == "no database pages listed"
    ours = dict(data["summary_groups"])["What concerns our ingredients"]
    assert [k for k, _ in ours][-1] == "Label databases read"
    # the label watch runs weekly: the daily report does not count it
    daily = rw.assemble(rw.gather_week(FakeDb(NOV5), NOV5), NOV5)
    assert "Label databases read" not in dict(daily["summary"])
