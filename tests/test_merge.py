"""Issue merging (plan, verification 5): one EMA DHPC plus its BfArM, ANSM and AIFA copies → one
issue with 4 documents. The copies are test documents built for this case."""

from __future__ import annotations

from datetime import date

from collectors.core.memstore import MemoryStore
from collectors.merge import DocFacts, compatible, merge_document, score

ING = "ing-lornoxicam"


def store_with_regulators() -> MemoryStore:
    s = MemoryStore()
    for rid, cc in (("EMA", "EU"), ("BFARM", "DE"), ("ANSM", "FR"), ("AIFA", "IT"), ("FDA", "US"),
                    ("PMDA", "JP")):
        s.upsert_regulator({"id": rid, "country_code": cc, "country_name": cc, "name": rid,
                            "languages": ["en"], "homepage": None})
    for sid, rid in (("ema-dhpc", "EMA"), ("bfarm-rhb", "BFARM"), ("ansm-securite", "ANSM"),
                     ("aifa-sicurezza", "AIFA"), ("fda-enforcement", "FDA"), ("pmda-revisions", "PMDA")):
        s.source[sid] = {"id": sid, "regulator_id": rid, "origin": "catalogue"}
    s.ingredient[ING] = {"inn_en": "lornoxicam", "active": True}
    return s


def add_doc(s: MemoryStore, source_id: str, title: str, published: date, text: str,
            doc_type: str = "dhpc", structured: dict | None = None, url: str = "") -> DocFacts:
    did = s.insert_document({"source_id": source_id, "external_id": title, "url": url or f"https://x/{title}",
                             "title_orig": title, "lang": None, "doc_type": doc_type,
                             "published_date": published, "structured": structured,
                             "is_backfill": False})
    s.insert_document_text(did, None, text)
    return DocFacts(document_id=did, source_id=source_id, country_code=s._country(source_id),
                    doc_type=doc_type, published=published, title=title, text=f"{title}\n{text}",
                    url=url or f"https://x/{title}", structured=structured, ingredient_ids={ING})


EMA_URL = "https://www.ema.europa.eu/en/medicines/dhpc/xefo"
EMA_STRUCT = {"name_of_medicine": "Xefo", "active_substances": "lornoxicam",
              "procedure_number": "EMEA/H/A-31/1599", "procedure_numbers": ["EMEA/H/A-31/1599"]}


def test_ema_dhpc_and_three_national_copies_make_one_issue():
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo - direct healthcare professional communication (DHPC)",
                     date(2026, 10, 1), "lornoxicam: risk of serious skin reactions", structured=EMA_STRUCT,
                     url=EMA_URL)
    r0 = merge_document(s, anchor, mahs=["Takeda"])
    assert r0.created

    copies = [
        add_doc(s, "bfarm-rhb", "Rote-Hand-Brief zu Xefo (Lornoxicam): Risiko schwerer Hautreaktionen",
                date(2026, 10, 6), "Verfahren EMEA/H/A-31/1599. Xefo enthält Lornoxicam."),
        add_doc(s, "ansm-securite", "Lornoxicam (Xefo) : risque de réactions cutanées graves",
                date(2026, 10, 9), f"Voir {EMA_URL}. Lornoxicam, Xefo."),
        add_doc(s, "aifa-sicurezza", "Nota informativa importante su Xefo (lornoxicam)",
                date(2026, 10, 20), "Medicinali contenenti lornoxicam (Xefo). Procedura EMEA/H/A-31/1599."),
    ]
    results = [merge_document(s, c, mahs=["Takeda"]) for c in copies]
    assert [r.created for r in results] == [False, False, False]
    assert {r.issue_id for r in results} == {r0.issue_id}
    assert len(s.issue) == 1
    links = s.documents_of(r0.issue_id)
    assert len(links) == 4
    assert sorted(x["link"] for x in links) == ["anchor", "copy", "copy", "copy"]
    assert all(x["method"] == "auto" for x in links)


def test_scores():
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    copy = add_doc(s, "bfarm-rhb", "RHB Xefo", date(2026, 10, 3), "EMEA/H/A-31/1599")
    total, reasons = score(anchor, copy)
    assert total == 6 and reasons == ["ema-procedure-or-link", "same-brand", "close-date"]
    far = add_doc(s, "bfarm-rhb", "Lornoxicam Hinweis", date(2026, 11, 25), "lornoxicam")
    assert score(anchor, far)[0] == 0


def test_weak_match_is_only_suggested():
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    r0 = merge_document(s, anchor, mahs=[])
    weak = add_doc(s, "ansm-securite", "Lornoxicam : information", date(2026, 10, 5), "lornoxicam Xefo")
    r = merge_document(s, weak, mahs=[])  # brand +2, close date +1 = 3 → suggestion
    assert r.created and r.suggested_to == [r0.issue_id]
    assert any(x["document_id"] == weak.document_id and x["method"] == "suggested"
               for x in s.documents_of(r0.issue_id))


def test_outside_eu_only_suggests():
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    r0 = merge_document(s, anchor, mahs=[])
    jp = add_doc(s, "pmda-revisions", "ロルノキシカム 使用上の注意の改訂", date(2026, 10, 10),
                 "Xefo EMEA/H/A-31/1599")
    r = merge_document(s, jp, mahs=[])
    assert r.created and r.suggested_to == [r0.issue_id]


def test_recall_never_merges_with_dhpc():
    assert not compatible("dhpc", "recall")
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    r0 = merge_document(s, anchor, mahs=[])
    recall = add_doc(s, "bfarm-rhb", "Rückruf Xefo", date(2026, 10, 2), "EMEA/H/A-31/1599 Xefo",
                     doc_type="recall")
    r = merge_document(s, recall, mahs=[])
    assert r.created and r.issue_id != r0.issue_id and not r.suggested_to


def test_late_anchor_adopts_national_issue():
    s = store_with_regulators()
    national = add_doc(s, "bfarm-rhb", "Rote-Hand-Brief zu Xefo", date(2026, 10, 3),
                       "EMEA/H/A-31/1599 Xefo")
    rn = merge_document(s, national, mahs=[])
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    ra = merge_document(s, anchor, mahs=[])
    assert not ra.created and ra.issue_id == rn.issue_id
    assert s.issue[rn.issue_id]["anchor_document_id"] == anchor.document_id
    assert sorted(x["link"] for x in s.documents_of(rn.issue_id)) == ["anchor", "copy"]


def test_a_copy_linked_to_an_ema_issue_adds_its_own_ingredients():
    s = store_with_regulators()
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    r0 = merge_document(s, anchor, mahs=[])
    copy = add_doc(s, "bfarm-rhb", "Rote-Hand-Brief zu Xefo plus", date(2026, 10, 3),
                   "EMEA/H/A-31/1599 Xefo, Lornoxicam und Paracetamol")
    copy.ingredient_ids = {ING, "ing-paracetamol"}
    r = merge_document(s, copy, mahs=[])
    assert not r.created and r.issue_id == r0.issue_id and r.link == "copy"
    assert r.alert                                    # whoever watches the new ingredient is told
    assert (r0.issue_id, "ing-paracetamol") in s.issue_ingredient


def test_a_fresh_anchor_takes_an_old_issue_out_of_the_backfill():
    s = store_with_regulators()
    national = add_doc(s, "bfarm-rhb", "Rote-Hand-Brief zu Xefo", date(2026, 10, 3),
                       "EMEA/H/A-31/1599 Xefo")
    national.is_backfill = True
    rn = merge_document(s, national, mahs=[])
    assert s.issue[rn.issue_id]["is_backfill"]
    anchor = add_doc(s, "ema-dhpc", "Xefo DHPC", date(2026, 10, 1), "", structured=EMA_STRUCT, url=EMA_URL)
    ra = merge_document(s, anchor, mahs=[])
    assert not ra.created and ra.issue_id == rn.issue_id and ra.alert
    assert s.issue[rn.issue_id]["is_backfill"] is False
