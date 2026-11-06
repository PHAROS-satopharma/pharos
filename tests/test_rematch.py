"""The check of the past (collectors/rematch.py): a word saved after the notices arrived is looked for in every
stored notice, whatever its date, as history, never as news. In-memory store and archive."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from collectors import rematch
from collectors.core.memstore import MemoryStore
from collectors.matching import Term

TODAY = date.today()
NOW = datetime.now(timezone.utc)
LEVO, LORNO, FQ = "ing-levofloxacin", "ing-lornoxicam", "class-fluoroquinolones"


class FakeArchive:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.reads: list[str] = []

    def put(self, key: str, content: bytes) -> str:
        self.objects[key] = content
        return key

    def get(self, key: str) -> bytes | None:
        self.reads.append(key)
        return self.objects.get(key)


def html(body: str) -> bytes:
    return f"<!doctype html><html><body><nav>Menu</nav><main><p>{body}</p></main></body></html>".encode()


def world() -> tuple[MemoryStore, FakeArchive]:
    s = MemoryStore()
    for rid, cc in (("EMA", "EU"), ("MPA", "SE"), ("ANSM", "FR"), ("NCBI", "INT")):
        s.upsert_regulator({"id": rid, "country_code": cc, "country_name": cc, "name": rid, "languages": ["en"],
                            "homepage": None})
    for sid, rid, kind in (("ema-dhpc", "EMA", "safety"), ("mpa-news", "MPA", "safety"),
                           ("ansm-securite", "ANSM", "safety"), ("pubmed", "NCBI", "literature")):
        s.source[sid] = {"id": sid, "regulator_id": rid, "kind": kind, "parser": "generic_html", "origin": "catalogue"}
    # lornoxicam was watched when the notices arrived: its word was already looked for
    s.ingredient[LORNO] = {"inn_en": "lornoxicam", "atc_code": "M01AC05", "active": True}
    s.terms.append(Term(id="t-lorno", term="lornoxicam", lang="en", ingredient_id=LORNO))
    return s, FakeArchive()


def add_levofloxacin(s: MemoryStore, *, with_class: bool = False) -> None:
    """Added after the notices arrived: its words are due."""
    s.ingredient[LEVO] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    for tid, term, lang in (("t-levo-en", "levofloxacin", "en"), ("t-levo-fr", "lévofloxacine", "fr"),
                            ("t-levo-sv", "Tavanic", "sv")):
        s.terms.append(Term(id=tid, term=term, lang=lang, ingredient_id=LEVO))
        s.term_state[tid] = {"changed_at": NOW - timedelta(hours=1), "rematched_at": None}
    if with_class:
        s.drug_class[FQ] = {"code": "J01MA", "name_en": "Fluoroquinolones", "origin": "atc", "wikidata_qid": "Q28801726"}
        s.ingredient_class.append((LEVO, FQ))
        s.terms.append(Term(id="ct-fq-sv", term="Fluorokinolon", lang="sv", class_id=FQ, kind="class"))
        s.term_state["ct-fq-sv"] = {"changed_at": NOW - timedelta(hours=1), "rematched_at": None}


def add_doc(s: MemoryStore, a: FakeArchive, source_id: str, title: str, *, days_ago: int = 90, lang: str = "en",
            original: bytes | None = None, mime: str = "text/html", kept: str | None = None,
            attachment: bytes | None = None, r2_key: str | None = None) -> str:
    did = s.insert_document({
        "source_id": source_id, "external_id": title, "url": f"https://example.test/{len(s.document)}",
        "title_orig": title, "lang": lang, "doc_type": "safety_alert",
        "published_date": TODAY - timedelta(days=days_ago), "structured": None,
        "r2_key": None, "mime": mime, "is_backfill": False})
    doc = s.document[did]
    doc["first_seen_at"] = NOW - timedelta(days=1)
    if original is not None:
        doc["r2_key"] = a.put(r2_key or f"raw/{did}", original)
    if kept is not None:
        s.insert_document_text(did, None, kept)
    if attachment is not None:
        s.insert_attachment({"document_id": did, "url": f"https://example.test/{did}.html", "filename": "a.html",
                             "sha256": None, "r2_key": a.put(f"att/{did}", attachment), "mime": "text/html",
                             "bytes": len(attachment), "extraction": "html", "words": 10})
    return did


def issue_of(s: MemoryStore, did: str) -> dict | None:
    link = next((x for x in s.issue_document if x["document_id"] == did and x["method"] != "suggested"), None)
    return s.issue[link["issue_id"]] if link else None


def test_new_ingredient_past_items_matched_as_history():
    s, a = world()
    page = add_doc(s, a, "ema-dhpc", "Fluoroquinolone antibiotics: aortic aneurysm",
                   original=html("Levofloxacin and ciprofloxacin: risk of aortic aneurysm and dissection."))
    pdf_like = add_doc(s, a, "ansm-securite", "Antibiotiques : rappel", lang="fr",
                       attachment=html("La lévofloxacine expose à un risque de tendinopathie."))
    nothing = add_doc(s, a, "ema-dhpc", "Paracetamol: dosing", original=html("Nothing about it."))
    old = add_doc(s, a, "ema-dhpc", "Dear healthcare professional letter", days_ago=4400,
                  original=html("Levofloxacin: tendon rupture, 2014."))
    paper = add_doc(s, a, "pubmed", "Levofloxacin tendinopathy: a cohort", original=html("levofloxacin"))
    add_levofloxacin(s)

    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])

    assert out.finished and out.matched == 3 and out.issues_created == 3
    for did in (page, pdf_like, old):
        iss = issue_of(s, did)
        assert iss is not None and iss["is_backfill"] is True and iss["class_only"] is False
        assert (iss["id"], LEVO) in s.issue_ingredient
    assert {m["term_id"] for m in s.match if m["document_id"] == page} == {"t-levo-en"}
    att = [m for m in s.match if m["document_id"] == pdf_like]
    assert {m["term_id"] for m in att} == {"t-levo-en", "t-levo-fr"}   # the INN finds the French spelling too
    assert all(m["field"] == "attachment" and m["attachment_id"] and m["matched_text"] == "lévofloxacine" for m in att)
    # the text read again is kept for the notices that now match, and only for them
    assert {t["document_id"] for t in s.document_text} == {page, pdf_like, old}
    assert "Menu" not in next(t["text"] for t in s.document_text if t["document_id"] == page)
    # a letter of 2014 is found too (the 12-month window missed 48 such notices); literature and notices that
    # do not name it: untouched
    assert {m["term_id"] for m in s.match if m["document_id"] == old} == {"t-levo-en"}
    for did in (nothing, paper):
        assert issue_of(s, did) is None
    assert f"raw/{paper}" not in a.reads
    # history: no message of any kind, and nothing for the daily digest
    assert s.notification == []
    assert s.class_only_issues_since(NOW - timedelta(days=30)) == []
    # the words are checked; the next run has nothing to do
    assert not any(s._due(t) for t in ("t-levo-en", "t-levo-fr", "t-levo-sv"))
    found = len(s.match)
    again = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert again.nothing_due and len(s.match) == found


def test_a_notice_that_already_has_an_issue_gains_the_ingredient_and_stays_as_it_was():
    s, a = world()
    did = add_doc(s, a, "ema-dhpc", "Lornoxicam and levofloxacin: interaction", kept="lornoxicam with levofloxacin")
    iid = s.create_issue(doc_type="safety_alert", title="x", anchor_document_id=did,
                         first_date=TODAY - timedelta(days=90), class_only=False, is_backfill=False)
    s.link_document(iid, did, link="anchor", method="auto", score=None)
    s.add_issue_ingredients(iid, [LORNO])
    s.insert_match({"document_id": did, "attachment_id": None, "ingredient_id": LORNO, "class_id": None,
                    "term_id": "t-lorno", "class_term_id": None, "field": "title", "start_offset": 0,
                    "end_offset": 10, "matched_text": "Lornoxicam", "snippet": "", "confidence": "high"})
    add_levofloxacin(s)

    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])

    assert out.matched == 1 and out.issues_created == 0 and out.reread == 0 and a.reads == []
    assert len(s.issue) == 1 and s.issue[iid]["is_backfill"] is False and "current_since" not in s.issue[iid]
    assert set(g for i, g in s.issue_ingredient if i == iid) == {LORNO, LEVO}
    assert sorted(m["term_id"] for m in s.match) == ["t-levo-en", "t-levo-en", "t-lorno"]  # title and kept text
    assert len(s.document_text) == 1   # the kept text is not stored twice


def test_class_words_find_class_only_history_for_the_class_ingredients():
    s, a = world()
    did = add_doc(s, a, "mpa-news", "Fluorokinoloner: begränsad användning", lang="sv",
                  original=html("Läkemedelsverket påminner om riskerna."))
    other_lang = add_doc(s, a, "ema-dhpc", "Fluorokinoloner", lang="en", original=html(""))
    add_levofloxacin(s, with_class=True)

    rematch.run(s, a, s.settings(), fields=lambda _p: [])

    iss = issue_of(s, did)
    assert iss is not None and iss["class_only"] is True and iss["is_backfill"] is True
    assert (iss["id"], LEVO) in s.issue_ingredient
    assert [m["class_term_id"] for m in s.match if m["document_id"] == did] == ["ct-fq-sv"]
    assert issue_of(s, other_lang) is None    # a Swedish class word only finds Swedish notices
    assert s.class_only_issues_since(NOW - timedelta(days=30)) == []


def test_a_list_page_shared_by_many_notices_is_not_read_as_each_notices_text():
    s, a = world()
    page = html("levofloxacin appears somewhere on the list")
    one = add_doc(s, a, "ema-dhpc", "Row one", original=page, r2_key="raw/list")
    two = add_doc(s, a, "ema-dhpc", "Row two", original=page, r2_key="raw/list")
    add_levofloxacin(s)
    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert out.matched == 0 and issue_of(s, one) is None and issue_of(s, two) is None and a.reads == []


def test_a_row_pharos_archived_itself_is_matched_by_its_fields_only():
    s, a = world()
    row = json.dumps({"source": "ema-dhpc", "item": {"title": "x", "notes": "levofloxacin"}}).encode()
    add_doc(s, a, "ema-dhpc", "A medicine row", original=row, mime="application/json")
    other = json.dumps({"results": [{"text": "Levofloxacin label update"}]}).encode()
    did = add_doc(s, a, "ema-dhpc", "An API answer", original=other, mime="application/json")
    add_levofloxacin(s)
    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert out.matched == 1 and issue_of(s, did) is not None


def test_it_stops_on_time_and_the_next_run_continues_where_it_stopped(monkeypatch):
    monkeypatch.setattr(rematch, "BATCH", 2)
    s, a = world()
    ids = [add_doc(s, a, "ema-dhpc", f"Notice {k}", original=html("levofloxacin" if k % 2 else "other"))
           for k in range(5)]
    add_levofloxacin(s)
    ticks = iter(range(100))
    out1 = rematch.run(s, a, s.settings(), fields=lambda _p: [], deadline=1, clock=lambda: next(ticks))
    job = s.rematch_open_job()
    assert not out1.finished and job is not None and job["documents_checked"] == 2
    assert job["cursor_document_id"] == sorted(ids)[1]
    assert s._due("t-levo-en")                     # not checked until the job reaches the end
    # a word changed while the job runs stays due for the next job
    s.term_state["t-levo-sv"]["changed_at"] = datetime.now(timezone.utc) + timedelta(seconds=1)
    out2 = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert out2.finished and out2.checked == 3
    done = next(iter(s.rematch_job.values()))
    assert done["finished_at"] is not None and done["documents_checked"] == 5
    assert done["documents_matched"] == 2 and done["issues_created"] == 2
    assert not s._due("t-levo-en") and s._due("t-levo-sv")
    assert sum(1 for d in ids if issue_of(s, d)) == 2
    # the next job takes only the changed word, and finds nothing new for it twice
    out3 = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    job3 = [j for j in s.rematch_job.values() if j["id"] != done["id"]][0]
    assert out3.finished and job3["ingredient_term_ids"] == ["t-levo-sv"] and out3.matched == 0


def test_a_paused_ingredient_is_not_checked_until_it_is_watched_again():
    s, a = world()
    add_doc(s, a, "ema-dhpc", "Levofloxacin: letter", original=html(""))
    add_levofloxacin(s)
    s.ingredient[LEVO]["active"] = False
    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert out.nothing_due and s.rematch_job == {}


def checked(s: MemoryStore, *term_ids: str) -> None:
    for tid in term_ids:
        s.term_state[tid] = {"changed_at": NOW - timedelta(days=2), "rematched_at": NOW - timedelta(days=2)}


def test_an_ingredient_linked_to_a_class_later_joins_the_class_only_issues_its_words_found():
    s, a = world()
    did = add_doc(s, a, "mpa-news", "Fluorokinoloner: begränsad användning", lang="sv", kept="Fluorokinoloner")
    add_levofloxacin(s, with_class=True)
    rematch.run(s, a, s.settings(), fields=lambda _p: [])
    iid = issue_of(s, did)["id"]
    assert {g for i, g in s.issue_ingredient if i == iid} == {LEVO}
    matches = len(s.match)
    moxi = "ing-moxifloxacin"
    s.ingredient[moxi] = {"inn_en": "moxifloxacin", "atc_code": "J01MA14", "active": True}

    s.link_ingredient_class(moxi, FQ)
    assert s.rematch_due_terms() == ([], ["ct-fq-sv"])     # the class's word is due again (0055)
    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])

    assert out.finished and out.matched == 1 and out.issues_created == 0
    assert {g for i, g in s.issue_ingredient if i == iid} == {LEVO, moxi}
    assert len(s.issue) == 1 and len(s.match) == matches   # the word is not matched to the notice twice
    assert s.notification == []
    assert rematch.run(s, a, s.settings(), fields=lambda _p: []).nothing_due


def test_a_class_word_is_looked_for_again_when_its_paused_ingredient_is_watched_again():
    s, a = world()
    add_levofloxacin(s, with_class=True)
    checked(s, "t-levo-en", "t-levo-fr", "t-levo-sv", "ct-fq-sv")
    s.ingredient[LEVO]["active"] = False     # paused: no one searched the class while the notice arrived
    did = add_doc(s, a, "mpa-news", "Fluorokinoloner: begränsad användning", lang="sv", kept="Fluorokinoloner")
    assert rematch.run(s, a, s.settings(), fields=lambda _p: []).nothing_due

    s.watch_again(LEVO)
    out = rematch.run(s, a, s.settings(), fields=lambda _p: [])

    iss = issue_of(s, did)
    assert out.matched == 1 and iss is not None and iss["class_only"] is True and iss["is_backfill"] is True
    assert (iss["id"], LEVO) in s.issue_ingredient


def test_a_link_switched_off_or_to_a_paused_ingredient_makes_nothing_due():
    s, a = world()
    add_levofloxacin(s, with_class=True)
    checked(s, "t-levo-en", "t-levo-fr", "t-levo-sv", "ct-fq-sv")
    s.ingredient["ing-paused"] = {"inn_en": "ofloxacin", "atc_code": "J01MA01", "active": False}
    s.link_ingredient_class("ing-paused", FQ)
    s.link_ingredient_class(LORNO, FQ, relation="parent", enabled=False)
    assert s.rematch_due_terms() == ([], [])


@pytest.mark.parametrize("months,expected_matches", [(12, 1), (24, 2), (None, 3)])
def test_months_sets_how_far_back_a_new_job_checks(months, expected_matches):
    s, a = world()
    add_doc(s, a, "ema-dhpc", "Levofloxacin: recent", days_ago=30, original=html(""))
    add_doc(s, a, "ema-dhpc", "Levofloxacin: last year", days_ago=500, original=html(""))
    add_doc(s, a, "ema-dhpc", "Levofloxacin: 2014", days_ago=4400, original=html(""))
    add_levofloxacin(s)
    out = rematch.run(s, a, s.settings(), months=months, fields=lambda _p: [])
    assert out.matched == expected_matches


def test_a_narrower_check_leaves_its_words_due_for_a_check_of_every_notice():
    """A check of 12 months by hand does not mark the words checked: the next (full) one still finds 2014."""
    s, a = world()
    recent = add_doc(s, a, "ema-dhpc", "Levofloxacin: recent", days_ago=30, original=html(""))
    old = add_doc(s, a, "ema-dhpc", "Levofloxacin: 2014", days_ago=4400, original=html(""))
    add_levofloxacin(s)
    first = rematch.run(s, a, s.settings(), months=12, fields=lambda _p: [])
    assert first.finished and first.matched == 1 and issue_of(s, old) is None
    assert all(s._due(t) for t in ("t-levo-en", "t-levo-fr", "t-levo-sv"))
    full = rematch.run(s, a, s.settings(), fields=lambda _p: [])
    assert full.finished and full.matched == 1 and issue_of(s, old)["is_backfill"] is True
    assert sum(1 for m in s.match if m["document_id"] == recent) == 1   # never matched twice for one word
    assert not any(s._due(t) for t in ("t-levo-en", "t-levo-fr", "t-levo-sv"))


def test_original_text_reads_pages_json_and_plain_text():
    assert "Levofloxacin" in rematch.original_text(html("Levofloxacin"), "text/html; charset=utf-8", "en")
    assert rematch.original_text(b'{"a": ["x", {"b": "levofloxacin"}], "n": 3}', "application/json", "en") == "x\nlevofloxacin"
    assert rematch.original_text(b"levofloxacin", "text/plain", "en") == "levofloxacin"
    assert rematch.original_text(None, "text/html", "en") == ""
    assert rematch.original_text(b"\x89PNG....", "image/png", "en") == ""
