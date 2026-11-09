"""Packs on request (the QPPV plan, phase 15): a PSUR pack for one ingredient, or an inspection pack, asked for on
Reports (request_report(), 0048) and built by the next collection run from the weekly report's own functions, in
chunks of at most 366 days, under a time budget, archived with its SHA-256 and told on Telegram (dry-run aware)."""
import io
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

from collectors import report, report_pack as rp
from collectors.alerts import Notifier
from collectors.core.archive import Archive, sha256_hex
from collectors.core.memstore import MemoryStore
from collectors.report import render_footer
from tests.test_report_weekly import LABEL_CHANGES, SIGNAL, _log, _mention, _page, _reg, _source

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
ING = "00000000-0000-4000-8000-000000000010"


class RecordingTelegram:
    """Must never be called: every test here is a dry run."""

    def __init__(self):
        self.calls = []

    def send_message(self, *a, **k):
        self.calls.append(("message", a, k))
        raise AssertionError("a pack test sent a real Telegram message")

    def send_document(self, *a, **k):
        self.calls.append(("document", a, k))
        raise AssertionError("a pack test sent a real Telegram document")


# ───────────────────────────── the days ─────────────────────────────

def test_the_days_are_read_in_chunks_of_at_most_366_days():
    pieces = rp.chunks(date(2024, 12, 2), date(2026, 11, 6))
    assert pieces[0][0] == date(2024, 12, 2) and pieces[-1][1] == date(2026, 11, 6)
    for (_, b), (c, _) in zip(pieces, pieces[1:], strict=False):
        assert c == b + timedelta(days=1)                   # no day skipped, none read twice
    assert all((b - a).days <= 365 for a, b in pieces)       # what ingredient_screen() answers in one call
    assert len(pieces) == 2
    assert rp.chunks(date(2026, 1, 1), date(2026, 12, 31)) == [(date(2026, 1, 1), date(2026, 12, 31))]
    assert len(rp.chunks(date(2021, 11, 7), date(2026, 11, 6))) == 5      # five years, the most a pack covers
    with pytest.raises(ValueError):
        rp.chunks(date(2026, 2, 1), date(2026, 1, 1))


def test_the_eurd_interval_is_worked_out_as_on_the_web():
    assert rp.frequency_months("7 years") == 84
    assert rp.frequency_months("6 months") == 6
    assert rp.frequency_months("1 year") == 12
    assert rp.frequency_months("") is None and rp.frequency_months("see notes") is None
    assert rp.interval_for("2026-12-01", "3 years") == (date(2023, 12, 2), date(2026, 12, 1))
    assert rp.interval_for(date(2024, 2, 29), "1 year") == (date(2023, 3, 1), date(2024, 2, 29))
    assert rp.interval_for(None, "3 years") is None
    # a DLP a short month cut (31 Aug and 28 Feb): the next DLP gives the day, so the interval starts on 1 Sep
    assert rp.interval_for(date(2027, 2, 28), "6 months", "2027-08-31") == (date(2026, 9, 1), date(2027, 2, 28))
    assert rp.interval_for("2026-11-30", "6 months", "2027-05-30") == (date(2026, 5, 31), date(2026, 11, 30))
    assert rp.interval_for("2026-03-15", "6 months", "2026-09-15") == (date(2025, 9, 16), date(2026, 3, 15))


def test_the_footer_fits_beside_the_credit():
    longest_month = len(report.Month(date(2026, 9, 1)).footer)
    psur = rp.Period("psur", date(2024, 12, 2), date(2026, 11, 6))
    insp = rp.Period("inspection", date(2025, 9, 30), date(2026, 9, 30))
    assert psur.footer == "PSUR pack · 2 Dec 2024 – 6 Nov 2026"
    assert insp.footer == "Inspection · 30 Sep 2025 – 30 Sep 2026"
    assert len(psur.footer) <= longest_month and len(insp.footer) <= longest_month
    assert "PHAROS · PSUR pack · 2 Dec 2024 – 6 Nov 2026" in render_footer(psur)
    a, b = insp.bounds_utc()
    assert a == datetime(2025, 9, 29, 21, tzinfo=UTC) and b == datetime(2026, 9, 30, 21, tzinfo=UTC)


def test_the_budget_runs_out():
    now = [0.0]
    budget = rp.Budget(lambda: now[0], seconds=10)
    budget.check()
    now[0] = 10.0
    with pytest.raises(rp.OutOfTime):
        budget.check()


# ───────────────────────────── a PSUR pack, gathered in two chunks ─────────────────────────────

PSUR_REQ = {"id": "11111111-1111-4111-8111-111111111111", "kind": "psur", "ingredient_id": ING,
            "from_day": date(2025, 1, 1), "to_day": date(2026, 3, 1), "requested_by": "p-rev",
            "requested_by_name": "Sama Hassan", "requested_at": datetime(2026, 11, 6, 8, tzinfo=UTC), "attempts": 1}
CHUNK1 = (date(2025, 1, 1), date(2026, 1, 1))
CHUNK2 = (date(2026, 1, 2), date(2026, 3, 1))

DECIDED = {"to_status": "relevant", "person": "Sama Hassan", "at": "2025-06-05T10:12:00Z",
           "comment": "Our product is named"}
NOT_OURS = {"to_status": "not_relevant", "person": "Sama Hassan", "at": "2025-07-01T09:00:00Z",
            "comment": "A veterinary product"}


def _regulators(chunk):
    if chunk == CHUNK1:
        return [_reg("BfArM", "Germany", "DE", runs=3, pages=[_page("BfArM", ["bfarm-src"])],
                     sources=[_source("bfarm-src", "BfArM")],
                     mentions=[_mention("d-1", "BfArM", "2025-06-04", "2025-06-04T08:00:00Z", issue_id="i-1",
                                        issue_status="relevant", decision=DECIDED)]),
                _reg("AIFA", "Italy", "IT", runs=2, pages=[_page("AIFA", ["aifa-src"])],
                     sources=[_source("aifa-src", "AIFA")],
                     mentions=[_mention("d-nr", "AIFA", "2025-07-01", "2025-07-01T08:00:00Z", issue_id="i-nr",
                                        issue_status="not_relevant", decision=NOT_OURS,
                                        link="javascript:alert(1)")])]
    return [_reg("BfArM", "Germany", "DE", runs=2, failed=1, pages=[_page("BfArM", ["bfarm-src"])],
                 sources=[_source("bfarm-src", "BfArM")],
                 mentions=[_mention("d-1", "BfArM", "2025-06-04", "2025-06-04T08:00:00Z", issue_id="i-1",
                                    issue_status="relevant", decision=DECIDED),
                           _mention("d-2", "BfArM", "2026-02-10", "2026-02-10T08:00:00Z")]),
            _reg("AIFA", "Italy", "IT", runs=1, pages=[_page("AIFA", ["aifa-src"])],
                 sources=[_source("aifa-src", "AIFA")])]


PAPERS = {
    CHUNK1: [{"document_id": "p-1", "title": "Tendon rupture after levofloxacin", "lang": "en", "journal": "Drug Saf",
              "day": date(2025, 5, 4), "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000001/", "pmc_url": None,
              "by_class": False, "is_backfill": False, "first_seen_at": datetime(2025, 5, 4, 6, tzinfo=UTC)},
             {"document_id": "p-3", "title": "Levofloxacin in children", "lang": "en", "journal": "",
              "day": date(2025, 8, 1), "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000003/", "pmc_url": None,
              "by_class": False, "is_backfill": False, "first_seen_at": datetime(2025, 8, 1, 6, tzinfo=UTC)}],
    CHUNK2: [{"document_id": "p-2", "title": "Aortic aneurysm after levofloxacin: a case report", "lang": "en",
              "journal": "BMJ Case Rep", "day": date(2026, 1, 20),
              "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/41000002/", "pmc_url": None, "by_class": False,
              "is_backfill": False, "first_seen_at": datetime(2026, 1, 20, 6, tzinfo=UTC)}],
}


class PsurDb:
    """Answers each query a PSUR pack makes, chunk by chunk, and keeps every statement."""

    def __init__(self):
        self.sql: list[tuple[str, dict]] = []
        self.chunks: list[tuple] = []
        self.finding_ids: list[list[str]] = []

    def _chunk(self, params):
        f, t = params["f"], params["t"]
        assert (t - f).days <= 365, "never more than 366 days in one call"
        assert (f, t) in (CHUNK1, CHUNK2)
        return (f, t)

    def fetchone(self, sql, params=None):
        self.sql.append((sql, params))
        if "from ingredient where id" in sql:
            assert params == {"i": ING}
            return {"id": ING, "inn_en": "levofloxacin", "atc_code": "J01MA12"}
        if "finding_state(" in sql:
            self.finding_ids.append(list(params["ids"]))
            sig = {**SIGNAL, "stage": "assessment", "priority": "high", "next_due": "2026-03-20",
                   "steps": SIGNAL["steps"] + [{"step": "validated", "from_stage": "validation",
                                                "to_stage": "assessment", "priority": "high", "outcome": None,
                                                "person": "Sama Hassan", "at": "2025-06-10T09:00:00Z",
                                                "comment": "Two more cases in the literature"}]}
            return {"f": {"i-1": {"clock": "sent", "due": "2025-06-09",
                                  "sent": {"on": "2025-06-08", "reference": "EDA/2025/0007"}, "signal": sig},
                          # the label change belongs to the same signal: it is listed once
                          "i-2": {"clock": "late", "due": "2025-10-25", "sent": None, "signal": sig},
                          "i-nr": {"clock": "off", "signal": None}}}
        chunk = self._chunk(params)
        assert params["i"] == ING
        if "ingredient_screen(" in sql:
            self.chunks.append(chunk)
            return {"screen": {"regulators": _regulators(chunk),
                               "literature": {"papers": len(PAPERS[chunk]), "by_name": len(PAPERS[chunk]),
                                              "by_class": 0, "pubmed": len(PAPERS[chunk]), "pmc": 0,
                                              "by_query": [{"query": "levofloxacin", "pubmed": len(PAPERS[chunk]),
                                                            "pmc": 0}]}}}
        if "label_changes(" in sql:
            return {"changes": [LABEL_CHANGES[0]] if chunk == CHUNK1 else []}
        if "literature_refs_week(" in sql:
            # Her literature references (0101), chunk by chunk: PubMed searched, nothing of the ingredient found
            # in the second chunk; Medscape and Al-Azhar checked by hand.
            return {"refs": [
                {"id": "r-pubmed", "scope": "global", "name": "PubMed (NCBI)", "url": "https://pubmed.ncbi.nlm.nih.gov/",
                 "by_hand": False, "searches": 300 if chunk == CHUNK1 else 65,
                 "name_searches": 150 if chunk == CHUNK1 else 30, "failed_reads": 0, "hits": 4,
                 "last_searched": "2025-11-06T04:00:00Z" if chunk == CHUNK1 else "2026-11-06T04:00:00Z",
                 "found": 2 if chunk == CHUNK1 else 0, "check": None},
                {"id": "r-cochrane", "scope": "global", "name": "Cochrane Database of Systematic Reviews",
                 "url": "javascript:alert(1)", "by_hand": False, "searches": 3, "name_searches": 3, "hits": 0,
                 "last_searched": "2025-11-06T04:00:00Z", "found": 0, "check": None},
                {"id": "r-medscape", "scope": "global", "name": "Medscape", "url": "https://www.medscape.com/",
                 "by_hand": True, "searches": 0, "hits": 0, "last_searched": None, "found": None, "check": None},
                {"id": "r-azhar", "scope": "local", "name": "Al-Azhar Medical Journal",
                 "url": "https://amj.journals.ekb.eg/", "by_hand": True, "searches": 0, "hits": 0,
                 "last_searched": None, "found": None, "check": None}]}
        raise AssertionError(f"unexpected query: {sql}")

    def fetchall(self, sql, params=None):
        self.sql.append((sql, params))
        if "from literature_check" in sql:
            assert params == {"f": CHUNK1[0], "t": CHUNK2[1]}
            return [{"ref_id": "r-medscape", "checks": 52, "found": 1, "last_at": "2026-11-04T08:00:00Z"}]
        if "ingredient_papers(" in sql:
            return PAPERS[self._chunk(params)]
        if "screening_log(" in sql:
            chunk = self._chunk(params)
            runs = 3 if chunk == CHUNK1 else 2
            return [_log("bfarm-src", "BfArM", "Germany", "safety", runs, failed=0 if chunk == CHUNK1 else 1,
                         why=None if chunk == CHUNK1 else "HTTP 503 from bfarm.example.test"),
                    _log("ncbi", "NCBI", "International", "literature", runs)]
        if "paper_state(" in sql:
            assert sorted(params["ids"]) == ["p-1", "p-2", "p-3"]
            return [{"state": {
                "p-1": {"issue_id": "i-p1", "issue_status": "not_relevant",
                        "decision": {"to_status": "not_relevant", "person": "Sama Hassan",
                                     "at": "2025-05-05T11:00:00Z", "comment": "Not our product"},
                        "case_report": None},
                "p-2": {"issue_id": "i-p2", "issue_status": "new", "decision": None,
                        "case_report": {"reason": "title"}, "day_zero": "2026-01-20", "due_serious": "2026-02-04",
                        "due_nonserious": "2026-04-20"},
                "p-3": {"issue_id": None}}}]
        if "mlm_monitored(" in sql:
            return [{"monitored": False}]
        if "from eurd_entry" in sql:
            return [{"eurd_id": 1, "substance": "levofloxacin", "combination": False, "frequency": "3 years",
                     "dlp": date(2026, 12, 1), "submission_date": date(2027, 2, 9), "next_dlp": date(2029, 12, 1),
                     "next_submission_date": None, "generics_psur_required": False, "procedure": "PSUSA/00001860",
                     "next_procedure": None, "lead_ms": "DE", "list_version": "EURD list 2026-10",
                     "list_date": date(2026, 10, 1)}]
        if "class_term" in sql:
            return [{"query": "levofloxacin", "kind": "name"}]
        raise AssertionError(f"unexpected query: {sql}")


def _psur():
    db = PsurDb()
    data = rp.assemble_psur(rp.gather_psur(db, PSUR_REQ), made_at=datetime(2026, 11, 6, 10, tzinfo=UTC))
    return db, data


def test_a_psur_pack_reads_every_chunk_and_adds_them_up():
    db, data = _psur()
    assert db.chunks == [CHUNK1, CHUNK2]
    germany = next(a for a in data["actions"] if a["country"] == "Germany")
    assert [m["title"] for m in germany["mentions"]] == ["Notice d-2", "Notice d-1"]     # each notice once
    assert [c["answer_text"] for c in data["countries"] if c["country"] == "Germany"] == ["Mentioned in 2 notices"]
    log = {r["source"]: r for r in data["annex"]}
    assert log["bfarm-src"]["runs"] == 5 and log["bfarm-src"]["failed"] == 1
    assert log["bfarm-src"]["why"] == "HTTP 503 from bfarm.example.test"
    # finding_state() is asked once for every finding of the pack
    assert sorted(set(db.finding_ids[0])) == ["i-1", "i-2", "i-nr", "i-p1", "i-p2"]


def test_a_psur_pack_answers_sections_3_4_11_and_15_16():
    _, data = _psur()
    m = next(m for a in data["actions"] for m in a["mentions"] if m["title"] == "Notice d-1")
    assert m["decision"] == "Concerns us" and m["decided_by"] == "Sama Hassan"
    assert m["sent_text"] == "Sent to the authority 8 Jun 2025 · EDA/2025/0007"
    assert m["signal"].startswith("SIG-2026-001 · Assessment, high priority")
    # §4: our label against the change
    assert [x["gap_summary"] for x in data["labels"]] == ["Our label: 2 covered, 1 partly, 1 missing"]
    # §11: the possible case report first
    papers = data["literature"]["papers"]
    assert [p["title"] for p in papers] == ["Aortic aneurysm after levofloxacin: a case report",
                                            "Levofloxacin in children"]
    assert papers[0]["case_report"] and papers[0]["day_zero"] == "20 Jan 2026"
    # §15–16: the one signal, once, with every step and both findings
    assert len(data["signals"]) == 1
    s = data["signals"][0]
    assert s["ref"] == "SIG-2026-001" and s["stage"] == "Assessment" and s["priority"] == "High"
    assert [e["step"] for e in s["steps"]] == ["Opened the signal", "Validated"]
    assert s["findings"] == ["Notice d-1", "Tavanic 500 mg — 4.4, 4.8"]
    assert data["eurd"][0]["interval"] == "2 Dec 2023 – 1 Dec 2026"


def test_the_psur_pack_gives_each_literature_reference_its_negative_result():
    # Dr Sama, 8 Nov 2026 (0101): each Global and Local reference over the pack's days, "Nothing found" in words.
    _, data = _psur()
    refs = {r["name"]: r for r in data["literature"]["refs"]}
    assert refs["PubMed (NCBI)"]["screened"] == "Searched by the app 365 times in these days, last 6 Nov 2026, 06:00"
    assert refs["PubMed (NCBI)"]["found"] == "2 papers"
    assert refs["Cochrane Database of Systematic Reviews"]["found"] == "Nothing found"
    assert refs["Cochrane Database of Systematic Reviews"]["url"] is None              # no javascript: link
    assert refs["Medscape"]["screened"] == "Checked by hand 52 times in these days, last 4 Nov 2026, 10:00"
    assert refs["Medscape"]["found"] == "Found something in 1 check"
    assert refs["Al-Azhar Medical Journal"]["screened"] == "Not checked by hand in these days"
    assert refs["Al-Azhar Medical Journal"]["scope"] == "Local"
    html = rp.render_pack_html(data)
    assert "Literature references, Global and Local" in html and "<strong>Nothing found</strong>" in html
    rows = list(load_workbook(io.BytesIO(rp.build_psur_xlsx(data)))["§11 References"].iter_rows(values_only=True))
    assert rows[0] == ("List", "Reference", "Link", "Screened", "Found")
    assert rows[4][:2] == ("Local", "Al-Azhar Medical Journal")


def test_findings_that_do_not_concern_us_are_counted_and_listed_apart():
    _, data = _psur()
    titles = [m["title"] for a in data["actions"] for m in a["mentions"]]
    assert "Notice d-nr" not in titles
    assert "Tendon rupture after levofloxacin" not in [p["title"] for p in data["literature"]["papers"]]
    assert [(r["section"], r["title"]) for r in data["not_relevant"]] == [
        ("§3 Regulatory actions", "Notice d-nr"), ("§11 Literature", "Tendon rupture after levofloxacin")]
    assert data["not_relevant_counts"] == [("§3 Regulatory actions", 1), ("§4 Label changes", 0),
                                           ("§11 Literature", 1)]
    assert ("Findings that do not concern us", 2) in data["summary"]


def test_the_psur_pdf_is_laid_out_by_psur_section():
    _, data = _psur()
    html = rp.render_pack_html(data)
    heads = re.findall(r'<h2><span class="n">(\d\d)</span>([^<]+)</h2>', html)
    assert heads == [("01", "Summary"), ("02", "§3 Regulatory actions"), ("03", "§4 Label changes"),
                     ("04", "§11 Literature"), ("05", "§15–16 Signals"), ("06", "Screening annex")]
    for words in ("PHAROS — PSUR pack · levofloxacin", "2 Dec 2023 – 1 Dec 2026", "Concerns us",
                  "Sent to the authority 8 Jun 2025 · EDA/2025/0007", "Two more cases in the literature",
                  "Our label: 2 covered, 1 partly, 1 missing", "Possible: its title says so",
                  "Findings that do not concern us", "HTTP 503 from bfarm.example.test", "Sama Hassan"):
        assert words in html, words
    assert "Notice d-nr" not in html and "javascript:" not in html
    assert report.CREDIT in html


def test_the_psur_excel_file_has_its_sheets_and_the_findings_left_out():
    _, data = _psur()
    wb = load_workbook(io.BytesIO(rp.build_psur_xlsx(data)))
    assert wb.sheetnames == list(rp.PSUR_SHEETS)
    for ws in wb.worksheets:
        assert "Sato Pharma" in (ws.oddFooter.left.text or ""), ws.title
    rows = list(wb["Not relevant"].iter_rows(values_only=True))
    assert [r[2] for r in rows[1:]] == ["Notice d-nr", "Tendon rupture after levofloxacin"]
    assert rows[1][3] in (None, "")                                   # no javascript: link
    assert rows[1][7] == "A veterinary product"
    sig = list(wb["§15-16 Signals"].iter_rows(values_only=True))
    assert sig[1][0] == "SIG-2026-001" and "Validated" in sig[1][11]


# ───────────────────────────── an inspection pack ─────────────────────────────

INSP_REQ = {"id": "22222222-2222-4222-8222-222222222222", "kind": "inspection", "ingredient_id": None,
            "from_day": date(2025, 11, 7), "to_day": date(2026, 11, 6), "requested_by": "p-adm",
            "requested_by_name": "Omar Gawish", "requested_at": datetime(2026, 11, 6, 8, tzinfo=UTC), "attempts": 1}
GOOD = "a" * 64


CAPA_ROWS = [  # what the CAPA plan reads (0107): opened in the days, or still open (not effective)
    {"id": "c1", "ref": "CAPA-001/2026", "year": 2026, "serial": 1, "source": "deviation", "deviation_ref": "D001/2026",
     "audit_title": None, "observation_number": None, "owner": "Sama Hassan", "due_on": date(2026, 6, 1),
     "done_on": date(2026, 5, 28), "status": "effective", "evidence": "PV-SOP-021 version 3",
     "verified_by": "Omar Gawish", "verified_at": datetime(2026, 6, 2, 9, tzinfo=UTC),
     "created_at": datetime(2026, 5, 5, 9, tzinfo=UTC)},
    {"id": "c2", "ref": "CAPA-002/2026", "year": 2026, "serial": 2, "source": "audit", "deviation_ref": None,
     "audit_title": "Partner Pharma 2026", "observation_number": 1, "owner": "Mona Adel", "due_on": date(2026, 10, 30),
     "done_on": None, "status": "in_progress", "evidence": None, "verified_by": None, "verified_at": None,
     "created_at": datetime(2026, 6, 9, 9, tzinfo=UTC)},                         # late by 7 days on 6 Nov
    {"id": "c3", "ref": "CAPA-003/2025", "year": 2025, "serial": 3, "source": "deviation", "deviation_ref": "D004/2025",
     "audit_title": None, "observation_number": None, "owner": "Ahmed (Regulatory)", "due_on": date(2026, 12, 1),
     "done_on": None, "status": "approved", "evidence": None, "verified_by": None, "verified_at": None,
     "created_at": datetime(2025, 9, 1, 9, tzinfo=UTC)},                         # opened before the days, still open
]


def _audit_row(title, kind, report, **done):
    return {"id": title, "kind": kind, "title": title, "auditor": "Partner Pharma", "lead_auditor": "Dr Lee",
            "report_received_on": report, "reviewed_on": None, "meeting_on": None, "capa_drafted_on": None,
            "capa_approved_on": None, "capa_submitted_on": None, "final_report_on": None,
            "closure_confirmed_on": None, "status": "report_received", "observations": [], **done}


AUDIT_ROWS = [
    # review on time, meeting 2 days late, draft on time, approval and submission never done: late
    _audit_row("Partner Pharma 2026", "external", date(2026, 6, 1), reviewed_on=date(2026, 6, 2),
               meeting_on=date(2026, 6, 5), capa_drafted_on=date(2026, 6, 10),
               observations=[{"number": 1, "text": "Signal log not reviewed monthly", "grade": "major",
                              "capas": [{"ref": "CAPA-002/2026", "status": "in_progress"}]}]),
    # report on 1 Nov: draft CAPA due 11 Nov, not yet
    _audit_row("Internal PV audit 2026", "internal", date(2026, 11, 1), reviewed_on=date(2026, 11, 2),
               meeting_on=date(2026, 11, 3)),
]


class InspectionDb:
    def __init__(self):
        self.sql: list[tuple[str, dict]] = []

    def _quality(self, sql, params):
        """The quality records of the days (0107), read chunk by chunk like the screening log."""
        if "from deviation d" in sql:
            assert (params["b"] - params["a"]) <= timedelta(days=367)
            at = datetime(2026, 5, 4, 9, tzinfo=UTC)
            return [{"id": "dv1", "ref": "D001/2026", "year": 2026, "serial": 1, "title": "Weekly report signed late",
                     "level": 2, "occurred_on": date(2026, 5, 3), "detected_on": date(2026, 5, 4), "created_at": at,
                     "root_cause": "No deputy named", "qa_satisfactory": True, "status": "approved",
                     "approved_at": datetime(2026, 5, 20, 9, tzinfo=UTC), "closed_at": None,
                     "capas": [{"ref": "CAPA-001/2026", "status": "effective"}]}] if params["a"] <= at < params["b"] else []
        if "from audit a" in sql:
            assert (params["t"] - params["f"]).days <= 365
            return [r for r in AUDIT_ROWS if params["f"] <= r["report_received_on"] <= params["t"]]
        if "from capa c" in sql:
            if "c.created_at >= %(a)s" in sql:
                assert (params["b"] - params["a"]) <= timedelta(days=367)
                return [r for r in CAPA_ROWS if params["a"] <= r["created_at"] < params["b"]]
            assert "c.status <> 'effective'" in sql
            return [r for r in CAPA_ROWS if r["status"] != "effective" and r["created_at"] < params["b"]]
        if "from quality_event" in sql:
            assert (params["b"] - params["a"]) <= timedelta(days=367)
            if not params["a"] <= datetime(2026, 6, 1, tzinfo=UTC) < params["b"]:
                return []
            return [{"record_kind": "deviation", "n": 9}, {"record_kind": "capa", "n": 7},
                    {"record_kind": "audit", "n": 4}, {"record_kind": "observation", "n": 1}]
        return None

    def fetchone(self, sql, params=None):
        self.sql.append((sql, params))
        if "from run where" in sql:
            return {"runs": 2190, "ok_runs": 2185}
        raise AssertionError(f"unexpected query: {sql}")

    def fetchall(self, sql, params=None):
        self.sql.append((sql, params))
        quality = self._quality(sql, params)
        if quality is not None:
            return quality
        if "screening_log(" in sql:
            assert (params["t"] - params["f"]).days <= 365
            return [_log("bfarm-src", "BfArM", "Germany", "safety", 2190, failed=5, why="HTTP 503")]
        if sql.strip().endswith("from regulator"):
            return [{"id": "BfArM", "name": "BfArM", "country_name": "Germany", "country_code": "DE",
                     "homepage": None},
                    {"id": "AIFA", "name": "AIFA", "country_name": "Italy", "country_code": "IT", "homepage": None}]
        if "from regulator_page" in sql:
            return [_page("BfArM", ["bfarm-src"]), _page("AIFA", [], label="AIFA DHPC letters")]
        if sql.strip().endswith("from source"):
            return [_source("bfarm-src", "BfArM")]
        if "from review_event re" in sql:
            return [{"created_at": datetime(2026, 6, 5, 10, 12, tzinfo=UTC), "from_status": "new",
                     "to_status": "relevant", "comment": "Our product is named", "person": "Sama Hassan",
                     "title": "Rote-Hand-Brief", "issue_id": "i-1"}]
        if "fingerprint_now" in sql:
            return [{"signed_at": datetime(2026, 6, 8, 9, tzinfo=UTC), "record_kind": "weekly_report",
                     "record_id": "w-1", "meaning": "approved", "signed_name": "Sama Hassan",
                     "signed_role": "admin", "comment": None, "record_sha256": GOOD, "week_start": date(2026, 5, 31),
                     "pack_kind": None, "from_day": None, "to_day": None, "month": None, "signal_ref": None,
                     "fingerprint_now": GOOD},
                    {"signed_at": datetime(2026, 7, 1, 9, tzinfo=UTC), "record_kind": "pack",
                     "record_id": "rq-1", "meaning": "reviewed", "signed_name": "Mona Adel",
                     "signed_role": "reviewer", "comment": "Read", "record_sha256": GOOD, "week_start": None,
                     "pack_kind": "psur", "from_day": date(2024, 1, 1), "to_day": date(2025, 12, 31), "month": None,
                     "signal_ref": None, "fingerprint_now": "b" * 64},
                    # a signal reads its fingerprint now only when the SQL has a branch for signals
                    {"signed_at": datetime(2026, 7, 2, 9, tzinfo=UTC), "record_kind": "signal",
                     "record_id": "sg-1", "meaning": "approved", "signed_name": "Sama Hassan",
                     "signed_role": "admin", "comment": None, "record_sha256": GOOD, "week_start": None,
                     "pack_kind": None, "from_day": None, "to_day": None, "month": None,
                     "signal_ref": "SIG-2026-001",
                     "fingerprint_now": GOOD if "when 'signal' then" in sql else None}]
        if "from authority_report ar" in sql:
            assert "withdrawn_at is null" not in sql            # a withdrawn report is evidence too
            return [{"sent_on": date(2026, 6, 8), "authority": "EDA", "reference": "EDA/2026/0042", "note": None,
                     "person": "Sama Hassan", "title": "Rote-Hand-Brief", "withdrawn_at": None,
                     "withdraw_reason": None, "withdrawn_by": None},
                    {"sent_on": date(2026, 6, 9), "authority": "EDA", "reference": None, "note": None,
                     "person": "Mona Adel", "title": "Rote-Hand-Brief", "withdrawn_at":
                         datetime(2026, 6, 9, 12, tzinfo=UTC), "withdraw_reason": "Sent twice",
                     "withdrawn_by": "Sama Hassan"}]
        if "from weekly_report w" in sql:
            return [{"id": "w-1", "week_start": date(2026, 5, 31), "week_end": date(2026, 6, 6), "pdf_sha256": "c" * 64,
                     "xlsx_sha256": "d" * 64, "made_at": datetime(2026, 6, 7, 2, tzinfo=UTC), "git_sha": "abc1234",
                     "made_by_run": "https://github.com/x/y/actions/runs/1", "fingerprint": GOOD,
                     "signatures": [{"name": "Sama Hassan", "role": "admin", "meaning": "approved",
                                     "at": "2026-06-08T09:00:00Z", "sha": GOOD}]}]
        if "from archive_check" in sql:
            return [{"checked_at": datetime(2026, 6, 1, 3, tzinfo=UTC), "sampled": 50, "mismatched": 0, "missing": 0,
                     "git_sha": "abc"}]
        if "from audit_log" in sql:
            return [{"table_name": "review_event", "action": "INSERT", "n": 12}]
        if "telegram_chat_id is not null as telegram" in sql:
            return [{"full_name": "Sama Hassan", "role": "admin", "active": True, "telegram": True,
                     "created_at": datetime(2026, 1, 1, tzinfo=UTC)},
                    {"full_name": "Mona Adel", "role": "reviewer", "active": True, "telegram": False,
                     "created_at": datetime(2026, 2, 1, tzinfo=UTC)}]
        raise AssertionError(f"unexpected query: {sql}")


def _inspection():
    db = InspectionDb()
    return db, rp.assemble_inspection(rp.gather_inspection(db, INSP_REQ), made_at=datetime(2026, 11, 6, tzinfo=UTC))


def test_an_inspection_pack_holds_the_evidence_of_the_days():
    db, data = _inspection()
    assert [(c["country"], c["status"]) for c in data["coverage"]] == [
        ("Germany", "Read by the app"), ("Italy", "Not read by the app — open it yourself")]
    assert [s["state"] for s in data["signatures"]] == ["Matches the file", "File changed since signing",
                                                       "Matches the file"]
    assert data["signatures"][1]["record"] == "PSUR pack, 1 Jan 2024 – 31 Dec 2025"
    assert data["signatures"][2]["record"] == "Signal SIG-2026-001"
    assert data["sent"][1]["withdrawn"].startswith("Withdrawn 9 Jun 2026, 15:00 by Sama Hassan: Sent twice")
    assert data["weekly"][0]["signed"] == ("Approved by Sama Hassan (Administrator), 8 Jun 2026, 12:00 — "
                                           "Matches the file")
    assert ("Reports to the authority", 1) in data["summary"]
    assert ("Of them, not read: checked by hand", 1) in data["summary"]
    assert data["people"][1]["role"] == "Reviewer"
    # the screening log is read in chunks of at most 366 days
    logs = [p for s, p in db.sql if "screening_log(" in s]
    assert [(p["f"], p["t"]) for p in logs] == [(date(2025, 11, 7), date(2026, 11, 6))]


def test_the_inspection_pdf_and_excel_file():
    _, data = _inspection()
    html = rp.render_pack_html(data)
    heads = re.findall(r'<h2><span class="n">(\d\d)</span>([^<]+)</h2>', html)
    assert heads == [("01", "Summary"), ("02", "Coverage"), ("03", "Screening log"),
                     ("04", "Decisions and signatures"), ("05", "Weekly reports"), ("06", "Audit log and people"),
                     ("07", "Quality: deviations, audits and CAPA")]
    for words in ("PHAROS — Inspection pack", "File changed since signing", "c" * 64, "Sent twice",
                  "Every file matched its SHA-256", "review_event", "Mona Adel"):
        assert words in html, words
    wb = load_workbook(io.BytesIO(rp.build_inspection_xlsx(data)))
    assert wb.sheetnames == list(rp.INSPECTION_SHEETS)
    weekly = list(wb["Weekly reports"].iter_rows(values_only=True))
    assert weekly[1][2] == "c" * 64 and weekly[1][3] == "d" * 64


# ───────────────────────────── the quality section (0107) ─────────────────────────────

def test_the_inspection_pack_holds_the_quality_records_of_the_days():
    _, data = _inspection()
    q = data["quality"]
    dev = q["deviations"][0]
    assert (dev["ref"], dev["level"], dev["detected"], dev["satisfactory"], dev["status"]) == (
        "D001/2026", "Level 2", "4 May 2026", "Satisfactory", "Approved by the QA Manager")
    assert dev["root_cause"] == "No deputy named" and dev["capas"] == "CAPA-001/2026 (Effective (closed))"
    # each audit deadline from the report day: on time, late, or not yet
    partner, internal = q["audits"]
    assert [(d["label"], d["due"], d["state"]) for d in partner["deadlines"]] == [
        ("QPPV review of the report", "2 Jun 2026", "on time"),
        ("Meeting with the responsible persons", "3 Jun 2026", "late"),
        ("Draft CAPA", "11 Jun 2026", "on time"),
        ("All CAPAs reviewed and approved", "13 Jun 2026", "late"),
        ("CAPA submitted", "15 Jun 2026", "late")]
    assert [d["state"] for d in internal["deadlines"]] == ["on time", "on time", "not yet", "not yet", "not yet"]
    assert partner["observations"][0]["grade"] == "Major"
    assert partner["observations"][0]["capas"] == "CAPA-002/2026 (In progress)"
    assert partner["closure"] == "Not closed (Report received)"
    # the CAPA plan: opened in the days or still open, once each; a late CAPA counted
    assert [c["ref"] for c in q["capas"]] == ["CAPA-003/2025", "CAPA-001/2026", "CAPA-002/2026"]
    assert [c["ref"] for c in q["capas"] if c["late"]] == ["CAPA-002/2026"]
    assert q["counts"] == {"open": 2, "late": 1, "closed": 1}
    c1 = next(c for c in q["capas"] if c["ref"] == "CAPA-001/2026")
    assert (c1["source"], c1["done"], c1["effective"], c1["evidence"]) == (
        "from D001/2026", "28 May 2026", "Verified 2 Jun 2026 by Omar Gawish", "PV-SOP-021 version 3")
    c2 = next(c for c in q["capas"] if c["ref"] == "CAPA-002/2026")
    assert c2["source"] == "from Audit Partner Pharma 2026, observation 1"
    # the history: rows per kind in the days, and that it cannot be changed
    assert q["history"] == [("Deviations", 9), ("Audits", 4), ("Audit observations", 1), ("CAPAs", 7)]
    assert q["history_total"] == 21
    for row in (("Deviations recorded", 1), ("Audits with a report", 2), ("CAPA open", 2), ("CAPA late", 1),
                ("CAPA closed (effective)", 1), ("Quality history rows", 21)):
        assert row in data["summary"], row


def test_the_quality_section_and_sheets_of_the_inspection_pack():
    _, data = _inspection()
    html = rp.render_pack_html(data)
    part = html[html.index("Quality: deviations, audits and CAPA"):]
    for words in ("D001/2026", "No deputy named", "Partner Pharma 2026", "Meeting with the responsible persons",
                  "CAPA-002/2026", "2 open, 1 late, 1 closed", "Signal log not reviewed monthly",
                  "cannot be changed"):
        assert words in part, words
    assert "PH409" not in part and "uuid" not in part.lower()
    wb = load_workbook(io.BytesIO(rp.build_inspection_xlsx(data)))
    assert wb.sheetnames[-3:] == ["Deviations", "Audits", "CAPA plan"]
    devs = list(wb["Deviations"].iter_rows(values_only=True))
    assert devs[1][0] == "D001/2026" and devs[1][2] == "Level 2"
    audits = list(wb["Audits"].iter_rows(values_only=True))
    assert audits[1][0] == "Partner Pharma 2026"
    assert "late" in audits[1][audits[0].index("Meeting with the responsible persons")]
    plan = list(wb["CAPA plan"].iter_rows(values_only=True))
    late = plan[0].index("Late")
    assert [(r[0], r[late] or "") for r in plan[1:]] == [("CAPA-003/2025", ""), ("CAPA-001/2026", ""),
                                                   ("CAPA-002/2026", "yes")]


def test_the_quality_records_are_read_in_chunks_of_at_most_366_days():
    db = InspectionDb()
    req = {**INSP_REQ, "from_day": date(2024, 11, 7)}                     # two years: two chunks
    data = rp.assemble_inspection(rp.gather_inspection(db, req), made_at=datetime(2026, 11, 6, tzinfo=UTC))
    devs = [p for s, p in db.sql if "from deviation d" in s]
    assert [(p["f"], p["t"]) for p in devs] == [(date(2024, 11, 7), date(2025, 11, 7)),
                                                (date(2025, 11, 8), date(2026, 11, 6))]
    assert len([1 for s, _ in db.sql if "from quality_event" in s]) == 2
    assert [d["ref"] for d in data["quality"]["deviations"]] == ["D001/2026"]          # once, never twice
    assert [c["ref"] for c in data["quality"]["capas"]] == ["CAPA-003/2025", "CAPA-001/2026", "CAPA-002/2026"]


# ───────────────────────────── built, archived and told ─────────────────────────────

@pytest.fixture()
def env(tmp_path, monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GIT_SHA", "abc123")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "PHAROS-satopharma/safety")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    printed = []
    monkeypatch.setattr(rp, "build_pdf", lambda html, footer: printed.append((html, footer)) or b"%PDF-1.7 pack")
    store = MemoryStore()
    store.person["p-rev"] = {"id": "p-rev", "full_name": "Sama Hassan", "telegram_chat_id": 111, "role": "reviewer",
                             "active": True}
    store.person["p-adm"] = {"id": "p-adm", "full_name": "Omar Gawish", "telegram_chat_id": 222, "role": "admin",
                             "active": True}
    store.person["p-read"] = {"id": "p-read", "full_name": "Reader", "telegram_chat_id": 333, "role": "reader",
                              "active": True}
    store.ingredient[ING] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    telegram = RecordingTelegram()
    archive = Archive(tmp_path / "archive")
    notifier = Notifier(store, store.settings(), dry_run=True, archive=archive, telegram=telegram)
    return {"store": store, "telegram": telegram, "archive": archive, "notifier": notifier, "printed": printed,
            "dir": tmp_path / "archive"}


def _ask(store, kind="psur", **extra):
    if kind == "psur":
        return store.add_report_request("psur", PSUR_REQ["from_day"], PSUR_REQ["to_day"], "p-rev",
                                        ingredient_id=ING, **extra)
    return store.add_report_request("inspection", INSP_REQ["from_day"], INSP_REQ["to_day"], "p-adm", **extra)


def test_nothing_waiting_does_nothing(env):
    assert rp.fulfil_requests(PsurDb(), env["store"], archive=env["archive"], notifier=env["notifier"]) is None
    assert env["store"].notification == [] and env["telegram"].calls == []


def test_a_pack_is_made_archived_and_told_to_who_asked_and_the_admins(env):
    store = env["store"]
    rid = _ask(store)
    out = rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert out["status"] == "done"
    row = store.report_request[rid]
    assert row["status"] == "done" and row["attempts"] == 1 and row["error"] is None
    stem = "PHAROS-PSUR-levofloxacin-2025-01-01-to-2026-03-01"
    assert row["pdf_r2_key"] == f"reports/packs/psur/{rid}/{stem}.pdf"
    assert row["xlsx_r2_key"] == f"reports/packs/psur/{rid}/{stem}.xlsx"
    assert row["pdf_sha256"] == sha256_hex(b"%PDF-1.7 pack") and len(row["xlsx_sha256"]) == 64
    assert row["git_sha"] == "abc123"
    assert row["made_by_run"] == "https://github.com/PHAROS-satopharma/safety/actions/runs/42"
    assert (env["dir"] / row["pdf_r2_key"]).read_bytes() == b"%PDF-1.7 pack"
    assert "PHAROS · PSUR pack · 1 Jan 2025 – 1 Mar 2026" in env["printed"][0][1]
    # the reviewer who asked and the administrator; never the reader; a dry run, never Telegram itself
    told = [(n["person_id"], n["kind"], n["dry_run"]) for n in store.notification]
    assert told == [("p-rev", "report", True), ("p-adm", "report", True)]
    assert "pack ready" in store.notification[0]["summary"]
    assert "PSUR pack, levofloxacin, 1 Jan 2025 – 1 Mar 2026" in store.notification[0]["summary"]
    assert env["telegram"].calls == []


def test_a_pack_made_again_never_overwrites_the_first(env):
    store = env["store"]
    first = _ask(store)
    rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"])
    # the same request id again (a build retried after it was archived): stored beside it
    store.report_request[first].update(status="queued")
    rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert store.report_request[first]["pdf_r2_key"].endswith("-r2.pdf")


def test_an_inspection_pack_is_made(env):
    store = env["store"]
    rid = _ask(store, "inspection")
    out = rp.fulfil_requests(InspectionDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert out["status"] == "done"
    assert store.report_request[rid]["pdf_r2_key"] == (
        f"reports/packs/inspection/{rid}/PHAROS-inspection-2025-11-07-to-2026-11-06.pdf")
    # the administrator asked: told once
    assert [n["person_id"] for n in store.notification] == ["p-adm"]
    # the quality section is in the pack, and nothing reached Telegram
    assert "Quality: deviations, audits and CAPA" in env["printed"][0][0]
    assert env["telegram"].calls == [] and all(n["dry_run"] for n in store.notification)


def test_an_inspection_pack_is_told_to_administrators_only(env):
    store = env["store"]
    # asked for before the reviewer's right was taken away: the reviewer is not told
    store.add_report_request("inspection", INSP_REQ["from_day"], INSP_REQ["to_day"], "p-rev")
    out = rp.fulfil_requests(InspectionDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert out["status"] == "done"
    assert [n["person_id"] for n in store.notification] == ["p-adm"]
    assert "pack ready" in store.notification[0]["summary"]


def test_a_pack_out_of_time_waits_for_the_next_run_then_fails_after_three(env):
    store = env["store"]
    rid = _ask(store)
    ticks = iter(range(0, 10_000, 100))

    def clock():
        return float(next(ticks))

    for attempt in (1, 2):
        out = rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"], clock=clock,
                                 budget_s=150)
        assert out["status"] == "queued"
        row = store.report_request[rid]
        assert row["status"] == "queued" and row["attempts"] == attempt
        assert row["error"] == "Took longer than 2 minutes; the next collection run goes on with it."
    assert store.notification == []                         # nobody is told of a pack still on its way
    out = rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"], clock=clock,
                             budget_s=150)
    assert out["status"] == "failed"
    row = store.report_request[rid]
    assert row["status"] == "failed" and row["attempts"] == 3 and "3 times" in row["error"]
    assert "pack not made" in store.notification[0]["summary"]
    assert not list(env["dir"].rglob("*.pdf"))              # nothing half made was archived


def test_a_pack_that_cannot_be_made_is_recorded_never_raised(env):
    store = env["store"]
    rid = _ask(store)

    class Broken(PsurDb):
        def fetchone(self, sql, params=None):
            if "ingredient_screen(" in sql:
                raise RuntimeError("canceling statement due to statement timeout")
            return super().fetchone(sql, params)

    out = rp.fulfil_requests(Broken(), store, archive=env["archive"], notifier=env["notifier"])
    assert out["status"] == "failed"
    row = store.report_request[rid]
    assert row["status"] == "failed" and "statement timeout" in row["error"]
    assert [n["person_id"] for n in store.notification] == ["p-rev", "p-adm"]
    assert "could not be made" in store.notification[0]["summary"]


def test_one_request_per_run_the_oldest_first(env):
    store = env["store"]
    old = _ask(store, "inspection", requested_at=datetime(2026, 11, 6, 7, tzinfo=UTC))
    new = _ask(store, requested_at=datetime(2026, 11, 6, 8, tzinfo=UTC))
    assert store.report_requests_waiting() == 2
    rp.fulfil_requests(InspectionDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert store.report_request[old]["status"] == "done" and store.report_request[new]["status"] == "queued"
    assert store.report_requests_waiting() == 1


def test_a_build_whose_run_died_is_taken_again_after_two_hours(env):
    store = env["store"]
    rid = _ask(store)
    store.report_request[rid].update(status="building", attempts=1,
                                     started_at=datetime.now(UTC) - timedelta(minutes=30))
    assert store.report_requests_waiting() == 0                 # another run may still be on it
    store.report_request[rid]["started_at"] = datetime.now(UTC) - timedelta(hours=3)
    assert store.report_requests_waiting() == 1
    rp.fulfil_requests(PsurDb(), store, archive=env["archive"], notifier=env["notifier"])
    assert store.report_request[rid]["status"] == "done" and store.report_request[rid]["attempts"] == 2


# ───────────────────────────── the workflow ─────────────────────────────

def test_packs_are_built_last_in_every_collection_run_but_never_stop_it():
    wf = (ROOT / ".github" / "workflows" / "collect.yml").read_text(encoding="utf-8")
    assert "python -m collectors.report_pack --waiting" in wf
    step = wf[wf.index("- name: Packs on request"):]
    assert "if: ${{ !cancelled()" in step.split("run:")[0]
    # a dry run never takes a real request: it would mark it done with nothing archived
    assert "&& !inputs.dry_run" in step.split("run:")[0]
    assert "timeout-minutes: 20" in step.split("run:")[0]
    assert "python -m collectors.report_pack" in step
    assert "::warning" in step                                  # a pack never fails the run
    assert "--dry-run" in step
    assert step.count("- name:") == 1, "the last step of the collection job"
    gate = wf[wf.index("- name: Packs waiting?"):wf.index("- name: Fonts for packs")]
    assert "!= 'weekly'" in gate and "!= 'classes'" in gate     # never in the label watch's 90 minutes
