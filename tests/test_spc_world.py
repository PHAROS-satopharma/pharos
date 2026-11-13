"""The label watch outside Europe: Korea (nedrug), Canada (Health Canada DPD) and New Zealand (Medsafe), read from
pages saved on 6 Nov 2026 (tests/fixtures/spc-nedrug, spc-hc-dpd, spc-medsafe; see their README files)."""

from __future__ import annotations

import json
from datetime import date

import pytest

from collectors.core.context import FetchError
from collectors.spc import hc_dpd, medsafe, nedrug, replay
from collectors.spc.common import SnapshotError
from collectors.spc.diff import diff_sections
from collectors.spc.run import MODULES
from collectors.spc.sections import kr_key, missing_core, split_ca_monograph, split_numbered, watched_changes
from tests.fakes_a2 import FakeCtx, fixture

IVABRADINE = {"id": "ing-iva", "inn_en": "ivabradine", "atc_code": "C01EB17", "terms": {"en": ["ivabradine"]}}
PARACETAMOL = {"id": "ing-par", "inn_en": "paracetamol", "atc_code": "N02BE01",
               "terms": {"en": ["paracetamol", "acetaminophen"]}}


def test_the_three_readers_are_watched():
    assert {MODULES[s] for s in ("spc-nedrug", "spc-hc-dpd", "spc-medsafe")} == {"nedrug", "hc_dpd", "medsafe"}


# ───────────────────────────── Korea ─────────────────────────────

def _search(term: str, page: int) -> str:
    return nedrug.SEARCH.format(term=term, page=page)


def test_korea_lists_the_two_procoralan_strengths():
    ctx = FakeCtx({_search("ivabradine", 1): "spc-nedrug/search_ivabradine.html"})
    got = nedrug.discover(ctx, IVABRADINE)
    assert got.complete
    assert [(p.national_id, p.product_name) for p in got] == [
        ("200906066", "프로코라란정5밀리그램(이바브라딘염산염)"), ("200906065", "프로코라란정7.5밀리그램(이바브라딘염산염)")]
    p = got[0]
    assert p.mah == "한국세르비에(주)" and p.country_code == "KR"
    assert p.extra["name_en"] == "Procoralan TAB 5mg" and p.extra["atc"] == "C01EB17"
    assert p.url == "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetail?itemSeq=200906066"


def test_korea_reads_only_the_result_rows_not_the_page_footer():
    # every page's footer links item 200500904; it is not a result
    rows = nedrug.parse_search(fixture("spc-nedrug/search_acetaminophen_p72.html").decode("utf-8"))
    assert len(rows) == 4 and "200500904" not in {r["seq"] for r in rows}
    assert nedrug.total_count(fixture("spc-nedrug/search_acetaminophen_p72.html").decode("utf-8")) == 1069


def test_korea_a_page_that_does_not_answer_leaves_the_list_partial():
    # acetaminophen: 1,069 products at 15 a page; page 72 answers, the first 71 do not
    ctx = FakeCtx({_search("acetaminophen", 72): "spc-nedrug/search_acetaminophen_p72.html"})
    got = nedrug.discover(ctx, {"id": "x", "inn_en": "acetaminophen", "terms": {"en": ["acetaminophen"]}})
    assert not got.complete and got.gaps == ["term 1 page 1: HTTP 404"]


def test_korea_keeps_a_row_only_when_an_ingredient_is_the_whole_word():
    assert nedrug.names_term("Acetaminophen/Aspirin/Anhydrous Caffeine", "acetaminophen")
    assert nedrug.names_term("Ivabradine Hydrochloride", "ivabradine")
    assert not nedrug.names_term("Dexibuprofen", "ibuprofen")


def test_korea_headings_by_their_words_not_their_numbers():
    assert kr_key("1. 다음 환자에는 투여하지 말 것.") == "kr:contraindications"
    assert kr_key("2. 다음 환자에는 투여하지 말 것.") == "kr:contraindications"     # the new format, after 1. 경고
    assert kr_key("1. 경고") == "kr:warning"
    assert kr_key("7. 과량 투여시의 처치") == "kr:overdose"
    assert kr_key("6. 임부 및 수유부에 대한 투여") == "kr:pregnancy"
    assert kr_key("3. 다음과 같은 경우 이 약의 복용을 즉각 중지하고 의사, 치과의사, 약사와 상의할 것") == "kr:stop_use"
    assert kr_key("9. 보관 및 취급상의 주의사항") == "kr:storage"
    assert kr_key("12. 무엇인가 새로운 것") == "kr:other"
    assert "kr:storage" not in watched_changes(["kr:storage"]) and watched_changes(["kr:other"]) == ["kr:other"]


def _korea_label_routes() -> dict:
    return {nedrug.HISTORY.format(seq="200906066", doc="NB"): "spc-nedrug/hist_200906066_NB.html",
            nedrug.DOC_XML.format(seq="200906066", doc="NB"): "spc-nedrug/drb_200906066_NB.xml",
            nedrug.DOC_XML.format(seq="200906066", doc="EE"): "spc-nedrug/drb_200906066_EE.xml",
            nedrug.DOC_XML.format(seq="200906066", doc="UD"): "spc-nedrug/drb_200906066_UD.xml"}


def test_korea_label_text_and_revision_date_come_from_the_change_history():
    ctx = FakeCtx(_korea_label_routes())
    snap = nedrug.snapshot(ctx, {"national_id": "200906066"})
    assert snap.doc_date == date(2017, 11, 10) and snap.lang == "ko"
    assert {"kr:contraindications", "kr:careful_use", "kr:adverse_reactions", "kr:general_precautions",
            "kr:interactions", "kr:pregnancy", "kr:overdose", "kr:driving", "kr:storage", "kr:indications",
            "kr:dosage"} == set(snap.sections)
    assert "심인성 쇼크 환자" in snap.sections["kr:contraindications"]
    assert "만성 심부전" in snap.sections["kr:indications"]
    asked = [u for m, u, _ in ctx.requests if m == "GET"]
    assert nedrug.DOC_XML.format(seq="200906066", doc="NB") not in asked      # the history gave the text


def test_korea_newest_history_version_is_the_published_label():
    newest, _ = nedrug.latest_history(fixture("spc-nedrug/hist_200906066_NB.html").decode("utf-8"))
    assert nedrug.doc_sections(newest, "NB") == nedrug.doc_sections(fixture("spc-nedrug/drb_200906066_NB.xml"), "NB")


def test_korea_without_history_reads_the_label_xml_with_no_date():
    routes = _korea_label_routes()
    routes[nedrug.HISTORY.format(seq="200906066", doc="NB")] = b"<html><table id='hist_list'></table></html>"
    snap = nedrug.snapshot(FakeCtx(routes), {"national_id": "200906066"})
    assert snap.doc_date is None and "kr:adverse_reactions" in snap.sections


def test_korea_a_label_part_that_does_not_answer_is_an_error_not_a_shorter_label():
    routes = _korea_label_routes()
    del routes[nedrug.DOC_XML.format(seq="200906066", doc="UD")]
    with pytest.raises(Exception, match="UD: HTTP 404"):
        nedrug.snapshot(FakeCtx(routes), {"national_id": "200906066"})


def test_korea_the_2017_revision_replays_as_a_change_in_three_watched_sections():
    # 23 Sep 2017 → 10 Nov 2017: general precautions, interactions and pregnancy changed; the adverse-reactions
    # table changed only its cell widths, which is no change
    versions = replay.nedrug_versions(fixture("spc-nedrug/hist_200906066_NB.html").decode("utf-8"))
    assert [d for d, _ in versions] == ["2017-11-10", "2017-09-23"]
    old, new = nedrug.doc_sections(versions[1][1], "NB"), nedrug.doc_sections(versions[0][1], "NB")
    changed = [c["section"] for c in diff_sections(old, new)]
    assert set(changed) == {"kr:general_precautions", "kr:interactions", "kr:pregnancy"}
    assert set(watched_changes(changed)) == set(changed)


def test_korea_replay_command_reads_the_history_once():
    ctx = FakeCtx({nedrug.HISTORY.format(seq="200906066", doc="NB"): "spc-nedrug/hist_200906066_NB.html"})
    result = replay.replay_nedrug(ctx, "200906066")
    assert result["versions"] == ("2017-09-23", "2017-11-10") and len(result["alerting"]) == 3


# ───────────────────────────── Canada ─────────────────────────────

def _canada_routes() -> dict:
    return {hc_dpd.MARKETED: "spc-hc-dpd/marketed_excerpt.json",
            hc_dpd.INGREDIENT.format(term="ivabradine"): "spc-hc-dpd/activeingredient_ivabradine.json",
            hc_dpd.INFO.format(code=94728): "spc-hc-dpd/info_94728.html",
            "https://pdf.hres.ca/dpd_pm/00080705.PDF": "spc-hc-dpd/pm_00080705.pdf"}


def test_canada_lists_the_marketed_lancora_strengths():
    got = hc_dpd.discover(FakeCtx(_canada_routes()), IVABRADINE)
    assert sorted((p.national_id, p.product_name) for p in got) == [("02459973", "LANCORA"),
                                                                    ("02459981", "LANCORA")]
    p = next(p for p in got if p.national_id == "02459973")
    assert p.mah == "SERVIER CANADA INC" and p.extra["drug_code"] == 94728
    assert hc_dpd.listed_version({"extra": p.extra}) == "2025-06-26"


def test_canada_keeps_marketed_human_products_only():
    market = hc_dpd.marketed(FakeCtx(_canada_routes()))
    assert 4204 not in market and {94728, 94729} <= set(market)       # 4204 is a veterinary product
    rows = json.loads(fixture("spc-hc-dpd/activeingredient_ivabradine.json"))
    assert hc_dpd.products_from(rows + [{"drug_code": 1, "ingredient_name": "IVABRADINE"}], market,
                                "ivabradine") and len(hc_dpd.products_from(rows, {}, "ivabradine")) == 0
    assert not hc_dpd.names_term("DEXIBUPROFEN", "ibuprofen")


def test_canada_a_list_that_does_not_answer_fails_the_discovery():
    routes = _canada_routes()
    del routes[hc_dpd.MARKETED]
    with pytest.raises(FetchError):
        hc_dpd.discover(FakeCtx(routes), IVABRADINE)


def test_canada_monograph_sections_and_date():
    snap = hc_dpd.snapshot(FakeCtx(_canada_routes()), {"national_id": "02459973", "extra": {"drug_code": 94728}})
    assert snap.doc_date == date(2025, 5, 30) and snap.source_url == "https://pdf.hres.ca/dpd_pm/00080705.PDF"
    assert {"ca:recent_major_changes", "ca:indications", "ca:contraindications", "ca:dosage", "ca:overdose",
            "ca:warnings_and_precautions", "ca:adverse_reactions", "ca:drug_interactions"} == set(snap.sections)
    assert "Resting heart rate below 70 beats per minute" in snap.sections["ca:contraindications"]
    assert "St John" in snap.sections["ca:drug_interactions"]
    # the patient information at the end is not read into the professional sections
    assert "Patient Medication Information" not in snap.sections["ca:drug_interactions"]
    assert not any("Page 1" in t for t in snap.sections.values())


def test_canada_a_product_without_a_monograph_has_no_label():
    # Benylin's own page (DIN 01944762, read 13 Nov 2026): "Electronic product monograph is not available", as for
    # all 68 of the 96 Canadian products that gave no text on 9 Nov (cough and cold remedies sold without one)
    routes = _canada_routes()
    routes[hc_dpd.INFO.format(code=12449)] = "spc-hc-dpd/info_12449.html"
    assert hc_dpd.snapshot(FakeCtx(routes), {"national_id": "01944762", "extra": {"drug_code": 12449}}) is None


def test_canada_a_page_with_neither_a_monograph_nor_its_absence_is_an_error():
    # a changed page must never pass for a product without a monograph
    routes = _canada_routes()
    routes[hc_dpd.INFO.format(code=94728)] = b"<html><p>Product name: X</p></html>"
    with pytest.raises(SnapshotError, match="neither a monograph link"):
        hc_dpd.snapshot(FakeCtx(routes), {"national_id": "02459973", "extra": {"drug_code": 94728}})


def test_canada_older_monograph_capital_headings():
    text = ("PRODUCT MONOGRAPH\nTABLE OF CONTENTS\nCONTRAINDICATIONS ........ 4\n"
            "INDICATIONS AND CLINICAL USE\nFor pain.\nCONTRAINDICATIONS\nLiver failure.\n"
            "The usual cautions (see\nWARNINGS AND PRECAUTIONS)\nWARNINGS AND PRECAUTIONS\nHepatotoxicity.\n"
            "ADVERSE REACTIONS\nRash.\nPART III: CONSUMER INFORMATION\nWARNINGS AND PRECAUTIONS\nAsk.\n")
    got = split_ca_monograph(text)
    assert got["ca:contraindications"].startswith("Liver failure.")
    assert got["ca:warnings_and_precautions"] == "Hepatotoxicity."
    assert got["ca:adverse_reactions"] == "Rash."


def test_canada_part_three_in_the_table_of_contents_is_not_the_end():
    # JAMP-Carvedilol (DIN 02368897, 13 Nov 2026): the contents line "PART III: PATIENT MEDICATION INFORMATION ....33"
    # ended the split at line 39, and four Canadian carvedilol monographs gave "no section heading found"
    text = ("PRODUCT MONOGRAPH\nTable of Contents\nPART I: HEALTH PROFESSIONAL INFORMATION ........ 3\n"
            "CONTRAINDICATIONS ........ 4\nPART III: PATIENT MEDICATION INFORMATION ..................33\n"
            "PART I: HEALTH PROFESSIONAL INFORMATION\nINDICATIONS AND CLINICAL USE\nHeart failure.\n"
            "CONTRAINDICATIONS\nAsthma.\nWARNINGS AND PRECAUTIONS\nBradycardia.\n"
            "PART III: PATIENT MEDICATION INFORMATION\nCONTRAINDICATIONS\nAsk.\n")
    got = split_ca_monograph(text)
    assert got["ca:indications"] == "Heart failure."
    assert got["ca:contraindications"] == "Asthma."
    assert got["ca:warnings_and_precautions"] == "Bradycardia."   # the real Part III still ends Part I


def test_canada_a_cross_reference_is_never_a_heading():
    text = ("1 Indications\nFor angina.\n2 Contraindications\nShock (see\n7 WARNINGS AND PRECAUTIONS).\n"
            "4 Dosage and Administration\n5 mg.\n7 Warnings and Precautions\nBradycardia.\n")
    got = split_ca_monograph(text)
    assert "7 WARNINGS AND PRECAUTIONS)." in got["ca:contraindications"]
    assert got["ca:warnings_and_precautions"] == "Bradycardia."


# ───────────────────────────── New Zealand ─────────────────────────────

def _nz_routes() -> dict:
    return {medsafe.LIST: "spc-medsafe/datasheet.htm", medsafe.UPDATES: "spc-medsafe/updates.html",
            medsafe.PDF_BASE + "p/panadolOsteocaplets.pdf": "spc-medsafe/panadolOsteocaplets.pdf"}


def test_new_zealand_finds_data_sheets_by_name_and_by_the_updates_page():
    got = {p.national_id: p for p in medsafe.discover(FakeCtx(_nz_routes()), PARACETAMOL)}
    assert got["a/ApoParacetamol665mgtab.pdf"].extra["found_by"] == "name"
    # "Panadol Osteo" names no ingredient; its CMI update of 6 Sep 2026 says it is paracetamol
    assert got["p/panadolOsteocaplets.pdf"].extra["found_by"] == "updates page"
    # Maxigesic's data sheet was updated on 18 Feb 2026: its listed version
    maxi = next(p for p in got.values() if p.product_name.startswith("Maxigesic"))
    assert medsafe.listed_version({"extra": maxi.extra}) == "2026-02-18"
    assert len(got) == 15


def test_new_zealand_reads_no_other_ingredient():
    assert medsafe.discover(FakeCtx(_nz_routes()), IVABRADINE) == []


def test_new_zealand_updates_page_rows():
    rows = medsafe.parse_updates(fixture("spc-medsafe/updates.html").decode("utf-8"))
    first = rows[0]
    assert first["date"] == date(2026, 11, 1) and first["data_sheet"] is False and first["trade"] == "Amgevita"
    assert any(r["data_sheet"] and r["trade"] == "Acetylcysteine (Martindale)" for r in rows)


def test_new_zealand_data_sheet_sections_and_revision_date():
    snap = medsafe.snapshot(FakeCtx(_nz_routes()), {"national_id": "p/panadolOsteocaplets.pdf"})
    assert {"4.3", "4.4", "4.8", "10"} <= set(snap.sections) and snap.doc_date == date(2025, 6, 11)


def test_new_zealand_a_list_that_does_not_answer_fails_the_discovery():
    routes = _nz_routes()
    del routes[medsafe.UPDATES]
    with pytest.raises(FetchError):
        medsafe.discover(FakeCtx(routes), PARACETAMOL)


# ───────────────────────────── every EU-numbered label ─────────────────────────────

def test_a_sentence_that_starts_with_a_section_number_is_not_a_heading():
    # a Dutch SmPC of 2024 (CBG h117827): "5.1 en 5.2, maar …" in 4.2 shut out 4.3–4.9 before 7 Nov 2026
    text = ("1. NAAM VAN HET GENEESMIDDEL\nX 5 mg\n4. KLINISCHE GEGEVENS\n4.1 Therapeutische indicaties\nAngina.\n"
            "4.2 Dosering en wijze van toediening\n"
            "Zie rubriek\n5.1 en 5.2, maar er kan geen doseringsadvies worden gegeven.\n4.3 Contra-indicaties\n"
            "Shock.\n4.4 Bijzondere waarschuwingen\nLet op.\n4.8 Bijwerkingen\nFosfenen.\n")
    got = split_numbered(text)
    assert got["4.3"] == "Shock." and got["4.8"] == "Fosfenen." and "5.1" not in got
    assert "5.1 en 5.2" in got["4.2"]


def test_a_split_without_a_core_section_is_never_a_label():
    assert missing_core({"4.3": "a", "4.4": "b", "4.8": "c"}) == []
    assert missing_core({"4.1": "a", "4.2": "b"}) == ["4.3", "4.4", "4.8"]
