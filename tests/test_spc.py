"""PHAROS — SPC / label watch (A2): section splitting, diffs, discovery from real fixtures, and the
snapshot → change → issue flow of ``collectors.spc.run`` against an in-memory database.

Fixtures (tests/fixtures/spc-*) were saved from the regulators on 4 Nov 2026. Section texts stay in
the label's own language; nothing is translated.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from collectors.core.context import FetchError
from collectors.core.models import Fetched
from collectors.spc import bdpm, cima, dailymed, ema_epar, mhra, pmda_pi
from collectors.spc.common import Product, Snapshot, SnapshotError, terms_for
from collectors.spc.diff import diff_sections, word_changes
from collectors.spc.run import canonical, change_title, watch_product
from collectors.spc.sections import (normalize, section_hash, split_japanese, split_numbered,
                                     watched_changes)
from tests.fakes_a2 import FakeCtx, SpcDb, fixture

CIMA = "https://cima.aemps.es/cima/rest"

# ───────────────────────────── sections ─────────────────────────────


def test_normalize_ignores_layout():
    assert normalize("riesgo  de\n lesión") == "riesgo de lesión"
    assert section_hash("lesión hepá-\ntica") == section_hash("lesión hepática")
    assert section_hash("a b") != section_hash("a c")


def test_split_numbered_spanish_smpc():
    text = "\n".join([
        "FICHA TÉCNICA",
        "1. NOMBRE DEL MEDICAMENTO",
        "Lornoxicam 8 mg comprimidos",
        "4. DATOS CLÍNICOS",
        "4.4 Advertencias y precauciones especiales de empleo",
        "Lornoxicam reduce la agregación plaquetaria.",
        "4.5 mg de lornoxicam por día no debe superarse.",       # a dose, not section 4.5
        "4.8 Reacciones adversas",
        "Náuseas.",
        "2 veces al día.",                                        # numbers must rise
        "5. PROPIEDADES FARMACOLÓGICAS",
        "Grupo farmacoterapéutico.",
    ])
    got = split_numbered(text)
    assert list(got) == ["1", "4", "4.4", "4.8", "5"]             # the cover line is dropped
    assert got["4.4"] == ("Lornoxicam reduce la agregación plaquetaria.\n"
                          "4.5 mg de lornoxicam por día no debe superarse.")
    assert got["4.8"] == "Náuseas.\n2 veces al día."
    assert got["1"] == "Lornoxicam 8 mg comprimidos"


def test_split_numbered_lower_case_top_heading_is_body():
    got = split_numbered("1. NOMBRE DEL MEDICAMENTO\nX\n4. DATOS CLÍNICOS\n4.4 Advertencias\n"
                         "Texto.\n5. después de comer\nMás.")
    assert "5" not in got
    assert got["4.4"] == "Texto.\n5. después de comer\nMás."


def test_split_japanese_new_format():
    text = "\n".join([
        "2026年10月改訂（第2版）",
        "1. 警告",
        "本剤は重篤な肝障害を起こすことがある。",
        "2. 禁忌（次の患者には投与しないこと）",
        "2.1 本剤の成分に対し過敏症の既往歴のある患者",
        "11. 副作用",
        "11.1 重大な副作用",
        "肝機能障害",
    ])
    got = split_japanese(text)
    assert got["ja:1"] == "本剤は重篤な肝障害を起こすことがある。"
    assert got["ja:2"] == "（次の患者には投与しないこと）\n2.1 本剤の成分に対し過敏症の既往歴のある患者"
    assert got["ja:11"] == "11.1 重大な副作用\n肝機能障害"
    assert got["ja:revision"] == "2026年10月改訂"


def test_split_japanese_old_format():
    got = split_japanese("【警告】\n注意A\n【禁忌（次の患者には投与しないこと）】\n注意B\n【使用上の注意】\n注意C")
    assert got == {"ja:1": "注意A", "ja:2": "注意B", "ja:precautions": "注意C"}


def test_split_japanese_new_format_section_3_ends_contraindications():
    # Headings as in the real insert of イブリーフ静注20mg (PMDA, revised Oct 2026): 3 組成・性状,
    # 5 and 7 (… に関連する注意) sit between the watched sections.
    text = "\n".join([
        "2. 禁忌（次の患者には投与しないこと）",
        "2.1 重篤な腎機能障害のある患者",
        "3. 組成・性状",
        "3.1 組成",
        "有効成分 イブプロフェン L-リシン 20mg",
        "4. 効能又は効果",
        "未熟児動脈管開存症",
        "5. 効能又は効果に関連する注意",
        "5.1 動脈管の閉鎖を確認すること。",
        "6. 用法及び用量",
        "通常、初回投与量は10mg/kg。",
        "7. 用法及び用量に関連する注意",
        "7.1 投与時間の上限は1時間を目安とすること。",
        "8. 重要な基本的注意",
        "8.1 最新の治療ガイドラインを参考にすること。",
    ])
    got = split_japanese(text)
    assert got["ja:2"] == "（次の患者には投与しないこと）\n2.1 重篤な腎機能障害のある患者"
    assert got["ja:3"] == "3.1 組成\n有効成分 イブプロフェン L-リシン 20mg"
    assert got["ja:4"] == "未熟児動脈管開存症"
    assert got["ja:5"] == "5.1 動脈管の閉鎖を確認すること。"
    assert got["ja:7"] == "7.1 投与時間の上限は1時間を目安とすること。"
    assert got["ja:8"] == "8.1 最新の治療ガイドラインを参考にすること。"
    # a composition change (new excipient) is not a contraindication change
    after = split_japanese(text.replace("20mg", "20mg 添加物 塩化ナトリウム"))
    changed = [c["section"] for c in diff_sections(got, after)]
    assert changed == ["ja:3"] and watched_changes(changed) == []


def test_split_japanese_old_format_insert():
    text = "\n".join([
        "2014年7月改訂（第8版）",
        "【禁忌（次の患者には投与しないこと）】",
        "消化性潰瘍のある患者",
        "【組成・性状】",
        "1錠中ロルノキシカム4mg",
        "【効能・効果】",
        "関節リウマチ",
        "【用法・用量】",
        "通常、成人に1回4mgを1日3回経口投与する。",
        "【使用上の注意】",
        "1. 慎重投与（次の患者には慎重に投与すること）",
        "2. 重要な基本的注意",
        "3. 副作用",
        "消化性潰瘍があらわれることがある。",
        "【薬物動態】",
        "健康成人に4mgを単回経口投与した。",
    ])
    got = split_japanese(text)
    assert got["ja:2"] == "消化性潰瘍のある患者"               # ends at 【組成・性状】
    assert got["ja:precautions"].endswith("消化性潰瘍があらわれることがある。")   # ends at 【薬物動態】
    assert "ja:8" not in got and "ja:11" not in got
    # a 副作用 change inside 【使用上の注意】 alerts; a change in 【用法・用量】 or 【薬物動態】 does not
    side = split_japanese(text.replace("あらわれることがある。", "あらわれることがある。肝機能障害。"))
    changed = [c["section"] for c in diff_sections(got, side)]
    assert watched_changes(changed) == ["ja:precautions"]
    dose = split_japanese(text.replace("1日3回", "1日2回").replace("単回", "反復"))
    changed = [c["section"] for c in diff_sections(got, dose)]
    assert changed and watched_changes(changed) == []


def test_watched_changes():
    changed = ["4.4", "4.2.1", "10", "5.1", "6.6", "ja:11", "ja:revision", "us:boxed_warning"]
    assert watched_changes(changed) == ["4.4", "4.2.1", "ja:11", "us:boxed_warning"]


# ───────────────────────────── diff ─────────────────────────────


def test_diff_sections_word_level():
    before = {"4.4": "Lornoxicam reduce la agregación plaquetaria.", "4.8": "Náuseas.",
              "10": "Junio 2023"}
    after = {"4.4": "Lornoxicam reduce la agregación plaquetaria. Riesgo de lesión hepática.",
             "4.8": "Náuseas.\n", "10": "Octubre 2026", "4.9": "Sin datos."}
    got = diff_sections(before, after)
    assert [c["section"] for c in got] == ["4.4", "4.9", "10"]   # 4.8 only changed layout
    ch = got[0]["changes"]
    assert ch == [{"op": "insert", "before": "", "after": "Riesgo de lesión hepática.",
                   "context": "Lornoxicam reduce la agregación plaquetaria."}]
    assert got[1]["before"] is None and got[1]["after"] == "Sin datos."


def test_diff_first_snapshot_is_no_change():
    assert diff_sections(None, {"4.4": "x"}) == []


def test_word_changes_japanese_joins_without_spaces():
    ch = word_changes("副作用：発疹", "副作用：発疹肝障害")
    assert ch == [{"op": "insert", "before": "", "after": "肝障害", "context": "副作用：発疹"}]


# ───────────────────────────── Spain, CIMA ─────────────────────────────


def test_cima_products_skip_revoked():
    data = json.loads(fixture("spc-cima/medicamentos.json"))
    assert len(cima.products_from(data, include_revoked=True)) == 7
    kept = cima.products_from(data)
    assert [p.national_id for p in kept] == ["78274"]
    p = kept[0]
    assert p.product_name == "LORNOXICAM RAPID MEIJI 8 MG COMPRIMIDOS RECUBIERTOS CON PELICULA EFG"
    assert p.mah == "Meiji Pharma Spain S.A."
    assert p.country_code == "ES"
    assert p.extra["segmented"] is True
    assert p.extra["ft_date"] == "2023-10-17"   # stamped 23:50 UTC on the 16th = 01:50 on the 17th in Madrid
    assert p.extra["ft_html"] == "https://cima.aemps.es/cima/dochtml/ft/78274/FT_78274.html"


def test_cima_document_date_is_the_day_in_spain():
    # 23:30 UTC on 4 March is 00:30 on the 5th in Madrid (UTC+1); 22:30 UTC on 4 July is 00:30 on the 5th (UTC+2).
    assert cima._ms_date(1772667000000) == date(2026, 3, 5)
    assert cima._ms_date(1783204200000) == date(2026, 7, 5)
    assert cima._ms_date(1772620200000) == date(2026, 3, 4)   # 10:30 UTC stays the same day
    assert cima._ms_date(None) is None


def test_cima_discover_by_atc():
    ctx = FakeCtx({CIMA + "/medicamentos?*": "spc-cima/medicamentos.json"})
    found = cima.discover(ctx, {"inn_en": "lornoxicam", "atc_code": "M01AC05", "terms": {}})
    assert [p.national_id for p in found] == ["78274"]
    assert ctx.requests[0][1] == CIMA + "/medicamentos?atc=M01AC05&pagina=1"


def test_cima_section_text():
    text = cima.section_text(fixture("spc-cima/contenido_65059_4.4.html").decode("utf-8"))
    assert text.startswith("Lornoxicam reduce la agregación plaquetaria")
    assert "<" not in text


def test_cima_snapshot_reads_watched_sections_only():
    ctx = FakeCtx({
        CIMA + "/docSegmentado/secciones/1?nregistro=65059": "spc-cima/secciones_65059.json",
        CIMA + "/docSegmentado/contenido/1?*": "spc-cima/contenido_65059_4.4.html",
    })
    snap = cima.snapshot(ctx, {"national_id": "65059", "extra": {"ft_date": "2023-10-16"}})
    assert sorted(snap.sections) == sorted(["4.1", "4.2", "4.2.1", "4.2.2", "4.3", "4.4", "4.5",
                                            "4.6", "4.6.1", "4.6.2", "4.6.3", "4.7", "4.8", "4.9",
                                            "10"])
    assert snap.sections["4.4"].startswith("Lornoxicam reduce la agregación plaquetaria")
    assert snap.lang == "es" and snap.doc_date == date(2023, 10, 16)
    asked = [r[1].rsplit("seccion=", 1)[-1] for r in ctx.requests if "contenido" in r[1]]
    assert "5.1" not in asked and "4.4" in asked


# ───────────────────────────── France, Japan, UK ─────────────────────────────


BDPM_IBU = {"inn_en": "ibuprofen", "terms": {"fr": ["IBUPROFÈNE"]}}


def _bdpm_ctx() -> FakeCtx:
    # Real rows of the two bulk files, Latin-1 with CRLF as the server sends them (fixture README).
    return FakeCtx({bdpm.COMPO_URL: "spc-bdpm/CIS_COMPO_slice.txt", bdpm.CIS_URL: "spc-bdpm/CIS_slice.txt"})


def test_bdpm_discovers_from_the_real_bulk_files():
    got = bdpm.discover(_bdpm_ctx(), BDPM_IBU)
    # active national products only: the abrogated one and the central (EU) PEDEA are left out,
    # the lysinate product is found through its ibuprofène FT row, paracetamol is not matched
    assert [p.national_id for p in got] == ["60073914", "64481322"]
    first = got[0]
    assert first.product_name == "IBUPROFENE BIOGARAN CONSEIL 400 mg, comprimé pelliculé"   # Latin-1 read right
    assert first.mah == "BIOGARAN"
    assert first.extra == {"commercialisation": "Commercialisée", "procedure": "Procédure nationale"}
    assert first.url == bdpm.HOST + "/medicament/60073914/extrait"


def test_bdpm_central_products_only_on_request():
    ctx = _bdpm_ctx()
    cis = bdpm.match_cis(bdpm._rows(ctx, bdpm.COMPO_URL), ["IBUPROFÈNE"])
    assert cis == {"60073914", "64481322", "62611169", "67747504"}
    got = bdpm.products_from(bdpm._rows(ctx, bdpm.CIS_URL), cis, include_central=True)
    assert [p.national_id for p in got] == ["60073914", "64481322", "67747504"]


def test_pmda_general_list():
    base = "https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/2190417"
    got = pmda_pi.parse_general_list(fixture("spc-pmda/general_list_2190417.html"), base)
    assert len(got) == 1
    p = got[0]
    assert p.national_id == "870276_2190417A1029"
    assert p.product_name == "イブリーフ静注20mg"
    assert p.mah == "製造販売（輸入）元／レコルダティ・レア・ディジーズ・ジャパン株式会社"
    assert p.url == ("https://www.pmda.go.jp/PmdaSearch/iyakuDetail/ResultDataSetPDF/"
                     "870276_2190417A1029_2_04")
    assert p.extra["package_id"] == "870276_2190417A1029_2_04"
    assert p.extra["pdf_date"] == "2026-10-27"
    assert p.country_code == "JP"


def test_mhra_plain_request_has_no_results():
    base = "https://products.mhra.gov.uk/search/?search=naproxen&page=1&doc=Spc&rerouteType=0"
    assert mhra.parse_results(fixture("spc-mhra/search_naproxen.html"), base) == []


def test_terms_for_falls_back_to_english_inn():
    ing = {"inn_en": "lornoxicam", "terms": {"ja": ["ロルノキシカム", "ロルノキシカム"]}}
    assert terms_for(ing, "ja") == ["ロルノキシカム"]
    assert terms_for(ing, "fr") == ["lornoxicam"]
    assert terms_for(ing, "fr", fallback_en=False) == []


# ───────────────────────────── run: snapshot → change → issue ─────────────────────────────


class _Module:
    """Hands ``watch_product`` one prepared snapshot per call."""

    def __init__(self, *snaps: Snapshot) -> None:
        self.snaps = list(snaps)

    def snapshot(self, ctx, product):
        return self.snaps.pop(0)


PRODUCT = {"id": "11111111-1111-1111-1111-111111111111", "national_id": "78274",
           "product_name": "LORNOXICAM RAPID MEIJI 8 MG COMPRIMIDOS RECUBIERTOS CON PELICULA EFG",
           "mah": "Meiji Pharma Spain S.A.", "country_code": "ES",
           "url": "https://cima.aemps.es/cima/publico/detalle.html?nregistro=78274"}
INGREDIENT = {"id": "22222222-2222-2222-2222-222222222222", "inn_en": "lornoxicam"}


def _snap(s44: str, s10: str = "Octubre 2023") -> Snapshot:
    return Snapshot(sections={"4.4": s44, "4.8": "Náuseas.", "10": s10},
                    doc_date=date(2026, 10, 30), lang="es", source_url=CIMA + "/x")


def test_canonical_is_order_independent():
    a = Snapshot(sections={"4.4": "x", "4.8": "y"}, lang="es")
    b = Snapshot(sections={"4.8": "y", "4.4": "x"}, lang="es")
    assert canonical(a) == canonical(b)


def test_watch_product_baseline_then_change_opens_one_issue():
    db, ctx = SpcDb(), FakeCtx()
    base = "Lornoxicam reduce la agregación plaquetaria."
    module = _Module(_snap(base), _snap(base),
                     _snap(base + " Riesgo de lesión hepática."),
                     _snap(base + " Riesgo de lesión hepática.", s10="Noviembre 2026"))

    assert watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT) is None   # baseline
    assert len(db.snapshots) == 1 and not db.changes and not db.issues

    assert watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT) is None   # unchanged
    assert len(db.snapshots) == 1

    issue = watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)          # 4.4 changed
    assert issue is not None
    assert len(db.snapshots) == 2 and len(db.issues) == 1 and len(db.documents) == 1
    doc = db.documents[0]
    assert doc["title"] == change_title(PRODUCT, ["4.4"])
    assert doc["title"] == PRODUCT["product_name"] + " — 4.4"
    assert doc["lang"] == "es" and doc["pub"] == date(2026, 10, 30)
    assert doc["structured"]["sections"] == ["4.4"]
    assert doc["ext"].startswith("spc:78274:")
    change = db.changes[0]
    assert change["s"] == ["4.4"] and change["i"] == issue
    assert change["f"] == db.snapshots[0]["id"] and change["t"] == db.snapshots[1]["id"]
    assert change["d"][0]["changes"][0]["after"] == "Riesgo de lesión hepática."
    assert {kind for kind, _ in db.links} == {"issue_document", "issue_ingredient"}
    assert db.matches[0]["g"] == INGREDIENT["id"]

    assert watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT) is None   # only 10
    assert len(db.issues) == 1
    assert db.changes[-1]["s"] == ["10"] and db.changes[-1]["i"] is None
    assert not db.gaps, "no label of ours: nothing to compare with"


def test_a_label_of_two_ingredients_is_watched_for_both_and_alerted_once():
    # Until 0079 a label belonged to the first ingredient that listed it: Japan's acetaminophen inserts sat
    # under ivabradine and paracetamol saw none (6 Nov 2026). A cold remedy is watched for each ingredient.
    from collectors.spc.run import upsert_product

    db, ctx = SpcDb(), FakeCtx()
    cold = Product(national_id="setid-cold", product_name="TYLENOL SINUS SEVERE", country_code="US")
    para = {"id": "44444444-4444-4444-4444-444444444444", "inn_en": "paracetamol"}
    guai = {"id": "55555555-5555-5555-5555-555555555555", "inn_en": "guaifenesin"}
    p1 = upsert_product(db, "spc-dailymed", para["id"], cold)
    p2 = upsert_product(db, "spc-dailymed", guai["id"], cold)
    assert p1["id"] != p2["id"] and p1["ingredient_id"] == para["id"] and p2["ingredient_id"] == guai["id"]
    assert upsert_product(db, "spc-dailymed", para["id"], cold)["id"] == p1["id"]    # read again: same row

    base = "Do not use with other medicines containing acetaminophen."
    module = _Module(_snap(base), _snap(base), _snap(base + " Stop use if skin reddening occurs."),
                     _snap(base + " Stop use if skin reddening occurs."))
    assert watch_product(db, ctx, module, "spc-dailymed", p1, para) is None           # baselines
    assert watch_product(db, ctx, module, "spc-dailymed", p2, guai) is None
    issue = watch_product(db, ctx, module, "spc-dailymed", p1, para)                  # 4.4 changed
    assert issue is not None
    assert watch_product(db, ctx, module, "spc-dailymed", p2, guai) is None           # same change: alerted once
    assert len(db.issues) == 1 and len(db.documents) == 1
    assert [c["i"] for c in db.changes] == [issue, issue]                              # both changes show it
    assert {p["g"] for kind, p in db.links if kind == "issue_ingredient"} == {para["id"], guai["id"]}
    assert {m["g"] for m in db.matches} == {para["id"], guai["id"]}


OUR_LABEL = {"id": "33333333-3333-3333-3333-333333333333", "ingredient_id": INGREDIENT["id"], "lang": "es",
             "sections": {"4.4": "Lornoxicam reduce la agregación plaquetaria. "
                                 "Riesgo de lesión hepática grave en tratamientos prolongados.",
                          "4.8": "Náuseas."}}


def test_a_change_is_compared_with_our_label_as_it_is_recorded():
    db, ctx = SpcDb(), FakeCtx()
    db.our_labels.append(OUR_LABEL)
    base = "Lornoxicam reduce la agregación plaquetaria."
    module = _Module(_snap(base), _snap(base + " Riesgo de lesión hepática."))
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)                  # baseline
    assert watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT) is not None
    assert len(db.changes) == 1 and len(db.gaps) == 1
    g = db.gaps[0]
    assert g["c"] == db.changes[0]["id"] and g["l"] == OUR_LABEL["id"]
    gap = g["gap"]
    assert gap["lang_match"] is True and gap["our_lang"] == "es" and gap["their_lang"] == "es"
    assert [s["section"] for s in gap["sections"]] == ["4.4"]
    added = gap["sections"][0]["added"]
    assert [a["sentence"] for a in added] == ["Riesgo de lesión hepática."]
    assert added[0]["status"] in ("covered", "partly") and "hepática" in added[0]["closest"]
    assert gap["covered"] + gap["partly"] == 1 and gap["missing"] == 0


def test_a_change_is_never_compared_with_our_label_in_another_language():
    db, ctx = SpcDb(), FakeCtx()
    db.our_labels.append({**OUR_LABEL, "lang": "en", "sections": {"4.4": "Risk of severe liver injury."}})
    base = "Lornoxicam reduce la agregación plaquetaria."
    module = _Module(_snap(base), _snap(base + " Riesgo de lesión hepática."))
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    assert len(db.gaps) == 1
    gap = db.gaps[0]["gap"]
    assert gap["lang_match"] is False and gap["sections"] == []
    assert (gap["our_lang"], gap["their_lang"]) == ("en", "es")


def test_a_failed_comparison_never_loses_the_change(monkeypatch):
    from collectors.labels import recompute

    def boom(*a, **k):
        raise RuntimeError("no label_gap table yet")

    monkeypatch.setattr(recompute, "gap_for_change", boom)
    db, ctx = SpcDb(), FakeCtx()
    db.our_labels.append(OUR_LABEL)
    base = "Lornoxicam reduce la agregación plaquetaria."
    module = _Module(_snap(base), _snap(base + " Riesgo de lesión hepática."))
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    assert watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT) is not None
    assert len(db.changes) == 1 and len(db.issues) == 1 and not db.gaps


def test_watch_product_without_archived_texts_compares_hashes():
    db, ctx = SpcDb(), FakeCtx()
    module = _Module(_snap("Texto A."), _snap("Texto B."))
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    ctx.archiver.objects.clear()                       # previous texts unreadable
    issue = watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    assert issue is not None
    assert db.changes[0]["s"] == ["4.4"]
    assert db.changes[0]["d"][0]["before"] is None


# ───────────────────────────── CIMA: one way of reading, one baseline ─────────────────────────────

SECC_65059 = CIMA + "/docSegmentado/secciones/1?nregistro=65059"
FT_65059 = "https://cima.aemps.es/cima/dochtml/ft/65059/FT_65059.html"
CIMA_PRODUCT = {**PRODUCT, "national_id": "65059",
                "extra": {"segmented": True, "ft_html": FT_65059, "ft_date": "2023-10-16"}}


def _cima_routes(sections_answer: bytes | str = "spc-cima/secciones_65059.json") -> dict:
    return {SECC_65059: sections_answer,
            CIMA + "/docSegmentado/contenido/1?*": "spc-cima/contenido_65059_4.4.html",
            FT_65059: "spc-cima/FT_65059.html"}


def test_cima_fallback_week_and_recovery_open_no_issue():
    # Week 1 per section; week 2 the section list answers [] and the full HTML is read (other keys,
    # other text); week 3 the API is back. None of that is a label change.
    db, ctx = SpcDb(), FakeCtx(_cima_routes())
    assert watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT) is None
    assert len(db.snapshots) == 1

    ctx.routes[SECC_65059] = b"[]"
    snap = cima.snapshot(ctx, CIMA_PRODUCT)
    assert snap.method == "html" and "4.2.1" not in snap.sections      # other keys than week 1
    assert watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT) is None
    assert len(db.snapshots) == 2 and not db.changes and not db.issues    # a new baseline

    ctx.routes[SECC_65059] = "spc-cima/secciones_65059.json"
    assert watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT) is None
    assert not db.changes and not db.issues                               # same as week 1


def test_cima_real_change_after_a_fallback_week_still_alerts():
    db, ctx = SpcDb(), FakeCtx(_cima_routes())
    watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT)
    ctx.routes[SECC_65059] = b"[]"
    watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT)
    ctx.routes[SECC_65059] = "spc-cima/secciones_65059.json"
    changed = fixture("spc-cima/contenido_65059_4.4.html") + "<p>Riesgo de lesión hepática.</p>".encode()
    ctx.routes[CIMA + "/docSegmentado/contenido/1?*"] = changed
    assert watch_product(db, ctx, cima, "spc-cima", CIMA_PRODUCT, INGREDIENT) is not None
    assert db.changes[-1]["f"] == db.snapshots[0]["id"]          # diffed against week 1, not 2


class ConditionalCtx(FakeCtx):
    """Like FetchContext: a URL already read in this run answers 304 with no content."""

    def get(self, url, **kwargs):
        seen = url in {r[1] for r in self.requests}
        f = super().get(url, **kwargs)
        return Fetched(304, url, b"", "") if seen and f.status == 200 else f


def test_cima_same_product_twice_in_one_run_reuses_the_first_read():
    # The same nregistro found for two ingredients: the second read gets 304 for every URL.
    ctx = ConditionalCtx(_cima_routes())
    first = cima.snapshot(ctx, CIMA_PRODUCT)
    second = cima.snapshot(ctx, CIMA_PRODUCT)
    assert second.method == first.method == "sections"
    assert second.sections == first.sections
    assert not any(r[1] == FT_65059 for r in ctx.requests)       # no fallback to the full HTML


def test_cima_missing_listed_section_fails_instead_of_partial_snapshot():
    ctx = FakeCtx({SECC_65059: "spc-cima/secciones_65059.json"})   # every contenido is a 404
    with pytest.raises(SnapshotError):
        cima.snapshot(ctx, CIMA_PRODUCT)


def test_snapshot_method_is_part_of_the_archived_form():
    a = Snapshot(sections={"4.4": "x"}, lang="es", method="sections")
    b = Snapshot(sections={"4.4": "x"}, lang="es", method="html")
    assert canonical(a) != canonical(b)
    assert canonical(Snapshot(sections={"4.4": "x"}, lang="es")) == \
        b'{"lang": "es", "sections": {"4.4": "x"}}'                 # other sources: unchanged


# ───────────────────────────── SPC failures are visible ─────────────────────────────


@pytest.fixture
def spc_world(monkeypatch):
    """A MemoryStore with the catalogue and an admin, SpcDb, and one fake module as spc-cima."""
    import sys
    import types

    from collectors.alerts import Notifier
    from collectors.core.memstore import MemoryStore
    from collectors.core.registry import sync_catalogue
    from collectors.spc import run as spc_run

    monkeypatch.setenv("DRY_RUN", "1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    store = MemoryStore()
    sync_catalogue(store)
    store.person["p2"] = {"id": "p2", "full_name": "Admin Two", "telegram_chat_id": 222,
                          "role": "admin", "active": True}
    store.subscription.append({"person_id": "p2", "kind": "admin_health", "ingredient_id": None})
    module = types.ModuleType("collectors.spc._fake_country")
    monkeypatch.setitem(sys.modules, "collectors.spc._fake_country", module)
    monkeypatch.setitem(spc_run.MODULES, "spc-cima", "_fake_country")
    monkeypatch.setattr(spc_run, "_sources", lambda db: ["spc-cima"])
    monkeypatch.setattr(spc_run, "_ingredients", lambda db, ids: [dict(INGREDIENT, terms={})])
    ctx = FakeCtx()
    ctx.run_id = "run-1"
    notifier = Notifier(store, store.settings(), telegram=None, dry_run=True)
    return store, SpcDb(), ctx, notifier, module


def _spc_runs(store, source_id="spc-cima"):
    return [r for r in store.source_run.values() if r["source_id"] == source_id]


def test_spc_failures_are_recorded_and_degrade_the_source(spc_world):
    from collectors.spc.run import DEGRADED_AFTER, run_spc

    store, db, ctx, notifier, module = spc_world

    def discover(ctx, ing):
        raise FetchError(503, "https://cima.aemps.es/cima/rest/medicamentos?atc=M01AC05")

    module.discover = discover
    for n in range(1, DEGRADED_AFTER + 2):
        assert run_spc(ctx, db, store=store, notifier=notifier) == []
        runs = _spc_runs(store)
        assert len(runs) == n and "HTTP 503" in runs[-1]["error"]
        assert store.source["spc-cima"]["consecutive_failures"] == n
    assert store.source["spc-cima"]["health"] == "degraded"
    health = [x for x in store.notification if x["kind"] == "health"]
    assert len(health) == 1 and health[0]["person_id"] == "p2"   # one alert, on the change


def test_spc_label_without_text_is_noted_and_a_good_run_is_ok(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: [Product(national_id="78274", product_name="X",
                                                country_code="ES"),
                                        Product(national_id="99999", product_name="Y",
                                                country_code="ES")]
    module.snapshot = lambda ctx, p: (None if p["national_id"] == "99999"
                                      else Snapshot(sections={"4.4": "Texto."}, lang="es"))
    run_spc(ctx, db, store=store, notifier=notifier)
    run = _spc_runs(store)[-1]
    assert run["items_seen"] == 2 and run["items_new"] == 1
    assert "1 product(s) without label text" in run["error"]
    assert store.source["spc-cima"]["health"] == "ok"


def test_spc_no_label_read_at_all_counts_as_a_failure(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: [Product(national_id="78274", product_name="X",
                                                country_code="ES")]

    def snapshot(ctx, p):
        raise SnapshotError("CIMA 78274 section 4.4: HTTP 500")

    module.snapshot = snapshot
    run_spc(ctx, db, store=store, notifier=notifier)
    assert store.source["spc-cima"]["consecutive_failures"] == 1
    assert "section 4.4: HTTP 500" in _spc_runs(store)[-1]["error"]


# ───────────────────────────── France, EU: a failed bulk read is not "no products" ──────────────


def test_bdpm_failed_bulk_file_raises_and_is_not_cached_as_empty():
    with pytest.raises(FetchError):
        bdpm.discover(FakeCtx(), BDPM_IBU)                           # 404 for the COMPO file
    assert [p.national_id for p in bdpm.discover(_bdpm_ctx(), BDPM_IBU)] == ["60073914", "64481322"]


# ───────────────────────────── United States, DailyMed ─────────────────────────────

DM_LIST = dailymed.API + "/spls.json?drug_name=meloxicam&doctype=34391-3&pagesize=100&page="
DM_EMPTY = "spc-dailymed/spls_meloxicam_otc_nda.json"      # DailyMed's own answer for an empty list


def _dm_otc(term: str, code: str) -> str:
    return (f"{dailymed.API}/spls.json?drug_name={term}&doctype=34390-5"
            f"&marketing_category_code={code}&pagesize=100&page=1")


def test_dailymed_discovers_human_prescription_labels_on_every_page():
    otc = {_dm_otc("meloxicam", c): DM_EMPTY for c in dailymed.OTC_APPROVED}
    ctx = FakeCtx({DM_LIST + "1": "spc-dailymed/spls_meloxicam_rx_p1.json",
                   DM_LIST + "2": "spc-dailymed/spls_meloxicam_rx_p2.json", **otc})
    got = dailymed.discover(ctx, {"inn_en": "meloxicam", "terms": {}})
    # doctype: no veterinary labels; then the three FDA-approved OTC lists, empty for meloxicam
    assert [r[1] for r in ctx.requests] == [DM_LIST + "1", DM_LIST + "2", *otc]
    assert len(got) == 186 and len({p.national_id for p in got}) == 186
    first = got[0]
    assert first.national_id == "445d7cbf-bd3e-a54f-e063-6294a90a67a5"
    assert first.product_name == "MELOXICAM TABLET [ADVANCED RX OF TENNESSEE, LLC]"
    assert first.url == "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=" + first.national_id
    assert first.country_code == "US" and first.extra["spl_version"] == 3


def test_dailymed_reads_a_prescription_list_past_five_pages():
    # Acetaminophen had 765 prescription labels on 6 Nov 2026: the old cap of 5 pages kept 500.
    def page(n: int) -> bytes:
        rows = [{"setid": f"rx-{n}-{i}", "title": f"ACETAMINOPHEN {n}-{i}", "spl_version": 1}
                for i in range(100 if n < 8 else 65)]
        return json.dumps({"data": rows, "metadata": {"total_pages": 8}}).encode()

    rx = dailymed.API + "/spls.json?drug_name=acetaminophen&doctype=34391-3&pagesize=100&page="
    ctx = FakeCtx({**{rx + str(n): page(n) for n in range(1, 9)},
                   **{_dm_otc("acetaminophen", c): DM_EMPTY for c in dailymed.OTC_APPROVED}})
    got = dailymed.discover(ctx, {"inn_en": "acetaminophen", "terms": {}})
    assert len(got) == 765


def test_dailymed_watches_the_otc_labels_fda_approves_and_not_the_monograph_ones():
    rx = dailymed.API + "/spls.json?drug_name=phenylephrine&doctype=34391-3&pagesize=100&page=1"
    ctx = FakeCtx({rx: DM_EMPTY,
                   _dm_otc("phenylephrine", "C73594"): "spc-dailymed/spls_phenylephrine_otc_nda.json",
                   _dm_otc("phenylephrine", "C73584"): "spc-dailymed/spls_phenylephrine_otc_anda.json",
                   _dm_otc("phenylephrine", "C73605"): "spc-dailymed/spls_phenylephrine_otc_ag.json"})
    got = dailymed.discover(ctx, {"inn_en": "phenylephrine", "terms": {}})
    assert len(got) == 8
    by_id = {p.national_id: p for p in got}
    assert by_id["7671d104-3c5c-4f63-b6b1-6c91c22592f8"].extra["otc_category"] == "C73594"   # Advil, NDA
    assert by_id["76513fb2-7323-4f1f-8a10-92f8f603cf97"].extra["otc_category"] == "C73584"   # Sudafed PE, ANDA
    asked = [r[1] for r in ctx.requests]
    assert all("34390-5" not in u or "marketing_category_code=" in u for u in asked)   # no monograph list


def test_dailymed_finds_paracetamol_by_its_rxnorm_code():
    # Paracetamol's English names are not the US name: by name it found none of acetaminophen's 765
    # prescription labels (6 Nov 2026). rxcui=161 finds them.
    rows = json.dumps({"data": [{"setid": "apap-1", "title": "ACETAMINOPHEN TABLET [X]", "spl_version": 1},
                                {"setid": "apap-2", "title": "TYLENOL (ACETAMINOPHEN) [Y]", "spl_version": 2}],
                       "metadata": {"total_pages": 1}}).encode()
    by_code = f"{dailymed.API}/spls.json?rxcui=161&doctype=34391-3&pagesize=100&page=1"
    ctx = FakeCtx({by_code: rows, f"{dailymed.API}/spls.json?*": DM_EMPTY})
    ing = {"inn_en": "paracetamol", "rxcui": "161",
           "terms": {"en": ["paracetamol", "4'-hydroxyacetanilide", "4-acetamidophenol", "acetaminophen"]}}
    got = dailymed.discover(ctx, ing)
    assert {p.national_id for p in got} == {"apap-1", "apap-2"}
    asked = [r[1] for r in ctx.requests]
    assert asked[0] == by_code and len(asked) == 4 * 4      # code + three names, each Rx and three OTC lists


def test_dailymed_a_failed_otc_list_fails_the_discovery():
    ctx = FakeCtx({DM_LIST + "1": "spc-dailymed/spls_meloxicam_rx_p1.json",
                   DM_LIST + "2": "spc-dailymed/spls_meloxicam_rx_p2.json"})   # OTC lists: 404
    with pytest.raises(FetchError):
        dailymed.discover(ctx, {"inn_en": "meloxicam", "terms": {}})


def test_dailymed_a_failed_page_fails_the_discovery():
    # A partial list would switch off every product on the pages that failed.
    ctx = FakeCtx({DM_LIST + "1": "spc-dailymed/spls_meloxicam_rx_p1.json"})   # page 2: 404
    with pytest.raises(FetchError):
        dailymed.discover(ctx, {"inn_en": "meloxicam", "terms": {}})


def test_dailymed_snapshot_of_a_real_label():
    setid = "445d7cbf-bd3e-a54f-e063-6294a90a67a5"
    ctx = FakeCtx({f"{dailymed.API}/spls/{setid}.xml": "spc-dailymed/spl_445d7cbf.xml"})
    snap = dailymed.snapshot(ctx, {"national_id": setid})
    assert snap.doc_date == date(2026, 11, 2) and snap.lang == "en"
    assert list(snap.sections) == ["us:recent_major_changes", "us:boxed_warning", "us:indications",
                                   "us:dosage_and_administration",
                                   "us:contraindications", "us:warnings_and_precautions",
                                   "us:adverse_reactions", "us:drug_interactions",
                                   "us:specific_populations", "us:overdosage"]
    assert snap.sections["us:boxed_warning"].startswith("Cardiovascular Thrombotic Events")
    assert "Hepatotoxicity" in snap.sections["us:warnings_and_precautions"]
    assert "Serious Skin Reactions" in snap.sections["us:recent_major_changes"]      # 7 Nov 2026: read too
    assert snap.method == dailymed.SECTIONS_2


def test_dailymed_snapshot_asks_as_dailymed_answers():
    # DailyMed refuses "Accept: application/xml" alone with HTTP 406 (6 Nov 2026), as this fake does
    setid = "445d7cbf-bd3e-a54f-e063-6294a90a67a5"

    class DailyMedCtx(FakeCtx):
        def get(self, url, *, accept=None, **kwargs):
            if accept == "application/xml":
                self.requests.append(("GET", url, None))
                return Fetched(406, url, b"", "application/json")
            return super().get(url, accept=accept, **kwargs)

    ctx = DailyMedCtx({f"{dailymed.API}/spls/{setid}.xml": "spc-dailymed/spl_445d7cbf.xml"})
    snap = dailymed.snapshot(ctx, {"national_id": setid})
    assert snap is not None and "us:boxed_warning" in snap.sections


EMA_SLICE = "spc-ema-epar/medicines_json_slice.json"


def test_ema_epar_catalogue_url_is_the_json_report():
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    assert next(s for s in sources if s.id == "spc-ema-epar").url == ema_epar.REPORT
    assert ema_epar.REPORT.endswith("/medicines-output-medicines_json-report_en.json")


def test_ema_epar_discovery_from_the_real_report():
    ctx = FakeCtx({ema_epar.REPORT: EMA_SLICE})
    found = ema_epar.discover(ctx, {"inn_en": "ibuprofen", "atc_code": None})
    assert [p.national_id for p in found] == ["EMEA/H/C/006129", "EMEA/H/C/000549"]  # not withdrawn
    assert found[1].product_name == "Pedea" and found[1].mah == "Recordati Rare Diseases"
    assert ema_epar.report_date(found[0].extra["last_updated"]) == date(2026, 11, 3)


def test_ema_epar_not_authorised_is_not_authorised():
    row = json.loads(fixture(EMA_SLICE))["data"][1]
    rows = [dict(row, medicine_status=s) for s in ("Not authorised", "Authorised")]
    got = ema_epar.products_from(rows, {"inn_en": "ibuprofen"})
    assert len(got) == 1


def test_ema_epar_failed_report_raises():
    with pytest.raises(FetchError):
        ema_epar.discover(FakeCtx(), {"inn_en": "ibuprofen"})


# ───────────────────────────── time: labels are read in turn ─────────────────────────────


class _Clock:
    """A clock that moves one second per label read, so a deadline falls between two labels."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _three_products(module, clock, *, reference: str | None = None):
    def discover(ctx, ing):
        return [Product(national_id=n, product_name=n, country_code="ES") for n in ("A1", "B2", "C3")]

    def snapshot(ctx, p):
        clock.t += 1
        return Snapshot(sections={"4.4": f"Texto {p['national_id']}."}, lang="es")

    module.discover, module.snapshot = discover, snapshot


def test_out_of_time_leaves_labels_for_the_next_run_which_reads_them_first(spc_world):
    # 6 Nov 2026: paracetamol's hundreds of products ran the weekly watch past GitHub's timeout.
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    clock, read = _Clock(), []
    _three_products(module, clock)
    inner = module.snapshot
    module.snapshot = lambda c, p: (read.append(p["national_id"]), inner(c, p))[1]
    run_spc(ctx, db, store=store, notifier=notifier, deadline=2, clock=clock)
    assert read == ["A1", "B2"]
    run = _spc_runs(store)[-1]
    assert "out of time: 1 label(s) left for the next run" in run["error"]
    assert store.source["spc-cima"]["health"] == "ok"            # time is never a failed run
    assert store.source["spc-cima"]["consecutive_failures"] == 0
    clock.t, read[:] = 0, []
    run_spc(ctx, db, store=store, notifier=notifier, deadline=1, clock=clock)
    assert read == ["C3"]                                          # the one never read goes first
    clock.t, read[:] = 0, []
    run_spc(ctx, db, store=store, notifier=notifier, deadline=2, clock=clock)
    assert read == ["A1", "B2"]                                    # then the one read longest ago


def test_our_reference_product_is_read_first(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    clock, read = _Clock(), []
    _three_products(module, clock)
    run_spc(ctx, db, store=store, notifier=notifier)               # no deadline: all three read
    for row in db.products.values():
        row["is_reference"] = row["national_id"] == "C3"
    inner = module.snapshot
    module.snapshot = lambda c, p: (read.append(p["national_id"]), inner(c, p))[1]
    clock.t = 0
    run_spc(ctx, db, store=store, notifier=notifier, deadline=1, clock=clock)
    assert read == ["C3"]


def test_a_label_that_failed_is_not_marked_read(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    clock = _Clock()
    _three_products(module, clock)
    inner = module.snapshot

    def snapshot(c, p):
        if p["national_id"] == "A1":
            raise SnapshotError("CIMA A1: HTTP 500")
        return inner(c, p)

    module.snapshot = snapshot
    run_spc(ctx, db, store=store, notifier=notifier)
    checked = {row["national_id"]: row.get("checked_at") for row in db.products.values()}
    assert checked["A1"] is None and checked["B2"] and checked["C3"]
    # the screen shows it as unread, with the error (0091) ...
    errors = {row["national_id"]: row.get("last_error") for row in db.products.values()}
    assert errors == {"A1": "SnapshotError: CIMA A1: HTTP 500", "B2": None, "C3": None}
    # ... until a run reads it
    module.snapshot = inner
    run_spc(ctx, db, store=store, notifier=notifier)
    assert all(row.get("last_error") is None for row in db.products.values())


def test_each_source_gets_its_share_of_the_time_left(spc_world, monkeypatch):
    import sys
    import types

    from collectors.spc import run as spc_run

    store, db, ctx, notifier, module = spc_world
    clock, read = _Clock(), []
    _three_products(module, clock)
    inner = module.snapshot
    module.snapshot = lambda c, p: (read.append(("ES", p["national_id"])), inner(c, p))[1]
    japan = types.ModuleType("collectors.spc._fake_japan")
    japan.discover = lambda c, ing: [Product(national_id="J1", product_name="J1", country_code="JP")]

    def jp_snapshot(c, p):
        clock.t += 1
        read.append(("JP", p["national_id"]))
        return Snapshot(sections={"4.4": "x"}, lang="ja")

    japan.snapshot = jp_snapshot
    monkeypatch.setitem(sys.modules, "collectors.spc._fake_japan", japan)
    monkeypatch.setitem(spc_run.MODULES, "spc-pmda", "_fake_japan")
    monkeypatch.setattr(spc_run, "_sources", lambda db: ["spc-cima", "spc-pmda"])
    spc_run.run_spc(ctx, db, store=store, notifier=notifier, deadline=2, clock=clock)
    assert read == [("ES", "A1"), ("JP", "J1")]                    # Spain stops at half; Japan is reached


# ───────────────────────────── a list that breaks off never switches products off ──────────────


def _two_products():
    return [Product(national_id="A", product_name="A 8 mg", country_code="ES"),
            Product(national_id="B", product_name="B 4 mg", country_code="ES")]


def _read_by(module):
    read: list[str] = []
    module.snapshot = lambda ctx, p: (read.append(p["national_id"])
                                      or Snapshot(sections={"4.4": f"Texto {p['national_id']}."}, lang="es"))
    return read


def test_spc_partial_list_switches_nothing_off_and_still_reads_the_rest(spc_world):
    from collectors.spc.common import Listing
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: _two_products()
    _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    module.discover = lambda ctx, ing: Listing(_two_products()[:1], gaps=["page 2: HTTP 304"])
    read = _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    assert {nid: r["active"] for (_s, _i, nid), r in db.products.items()} == {"A": True, "B": True}
    assert sorted(read) == ["A", "B"]                      # B, which the list did not reach, is read too
    run = _spc_runs(store)[-1]
    assert "partial list: page 2: HTTP 304" in run["error"] and run["items_seen"] == 2
    # the screen says the list broke off, and where (spc_listing, 0091)
    assert list(db.listings.values()) == [{"products": 2, "complete": False, "gaps": "page 2: HTTP 304"}]


def test_spc_complete_list_still_switches_off_a_withdrawn_product(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: _two_products()
    _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    module.discover = lambda ctx, ing: _two_products()[:1]
    run_spc(ctx, db, store=store, notifier=notifier)
    assert {nid: r["active"] for (_s, _i, nid), r in db.products.items()} == {"A": True, "B": False}
    assert list(db.listings.values()) == [{"products": 1, "complete": True, "gaps": None}]


def test_spc_empty_list_after_products_is_a_failed_discovery(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: _two_products()
    _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    module.discover = lambda ctx, ing: []
    read = _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    assert all(r["active"] for r in db.products.values())
    assert sorted(read) == ["A", "B"]
    assert "listed no product; 2 listed before kept" in _spc_runs(store)[-1]["error"]
    assert store.source["spc-cima"]["consecutive_failures"] == 1     # not an ok discovery


def test_spc_failed_discovery_still_reads_the_known_labels(spc_world):
    from collectors.spc.run import run_spc

    store, db, ctx, notifier, module = spc_world
    module.discover = lambda ctx, ing: _two_products()
    _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)

    def discover(ctx, ing):
        raise FetchError(503, "https://cima.aemps.es/cima/rest/medicamentos?atc=M01AC05")

    module.discover = discover
    read = _read_by(module)
    run_spc(ctx, db, store=store, notifier=notifier)
    assert sorted(read) == ["A", "B"]
    assert "HTTP 503" in _spc_runs(store)[-1]["error"]
    (listing,) = db.listings.values()
    assert listing["products"] == 2 and not listing["complete"]
    assert listing["gaps"].startswith("the list failed: FetchError") and "2 listed before kept" in listing["gaps"]


class ValidatorCtx(FakeCtx):
    """Like FetchContext: a URL already read in this run answers 304, until ``forget`` asks for it in full."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.validated: set[str] = set()

    def get(self, url, **kwargs):
        f = super().get(url, **kwargs)
        if url in self.validated and f.status == 200:
            return Fetched(304, url, b"", "")
        if f.status == 200:
            self.validated.add(url)
        return f

    def forget(self, url):
        super().forget(url)
        self.validated.discard(url)


def test_a_label_shared_by_two_ingredients_is_read_in_full_for_both():
    # 0079: one cold remedy is a product of paracetamol and of phenylephrine; the second read in the same run
    # was a bare 304, stored as "no label text" for the second ingredient.
    setid = "445d7cbf-bd3e-a54f-e063-6294a90a67a5"
    ctx = ValidatorCtx({f"{dailymed.API}/spls/{setid}.xml": "spc-dailymed/spl_445d7cbf.xml"})
    first = dailymed.snapshot(ctx, {"national_id": setid})
    second = dailymed.snapshot(ctx, {"national_id": setid})
    assert first.sections and second.sections == first.sections


def test_a_label_that_does_not_answer_is_an_error_not_no_text():
    ctx = ValidatorCtx({})
    with pytest.raises(SnapshotError):
        dailymed.snapshot(ctx, {"national_id": "gone"})


def test_pmda_code_page_that_does_not_answer_makes_a_partial_list(monkeypatch):
    monkeypatch.setattr(pmda_pi, "code_sources", lambda ctx, ing: {"2190417": True, "1149036": True})

    class Ctx(FakeCtx):
        def get(self, url, **kwargs):
            if url.endswith("1149036"):
                self.requests.append(("GET", url, None))
                return Fetched(304, url, b"", "")
            return super().get(url, **kwargs)

    found = pmda_pi.discover(Ctx({pmda_pi.GENERAL.format(code="2190417"):
                                  "spc-pmda/general_list_2190417.html"}), {"inn_en": "x", "terms": {}})
    assert found and not found.complete and "HTTP 304" in found.gaps[0]


def test_cima_page_that_does_not_answer_fails_the_discovery():
    class Ctx(FakeCtx):
        def get(self, url, **kwargs):
            if "pagina=2" in url:
                return Fetched(304, url, b"", "")
            return super().get(url, **kwargs)

    data = json.loads(fixture("spc-cima/medicamentos.json"))
    data.update(totalFilas=400, tamanioPagina=200, pagina=1)
    ctx = Ctx({CIMA + "/medicamentos?*": json.dumps(data).encode()})
    with pytest.raises(FetchError):
        cima.discover(ctx, {"inn_en": "lornoxicam", "atc_code": "M01AC05", "terms": {}})


def test_cima_searches_the_spanish_name_too_for_combinations():
    ctx = FakeCtx({CIMA + "/medicamentos?*": "spc-cima/medicamentos.json"})
    cima.discover(ctx, {"inn_en": "lornoxicam", "atc_code": "M01AC05", "terms": {"es": ["lornoxicam"]}})
    urls = [r[1] for r in ctx.requests]
    assert CIMA + "/medicamentos?practiv1=LORNOXICAM&pagina=1" in urls


# ───────────────────────────── versions, US precautions, an EPAR with several SmPCs (7 Nov 2026) ──────────


def test_an_epar_with_two_smpcs_reads_each_on_its_own():
    from collectors.spc.sections import split_smpc_sections, watched_changes

    one = ("1. NAME OF THE MEDICINAL PRODUCT\nProcoralan 5 mg film-coated tablets\n"
           "4. CLINICAL PARTICULARS\n4.4 Special warnings and precautions for use\nBradycardia 5 mg.\n"
           "6. PHARMACEUTICAL PARTICULARS\n6.1 List of excipients\nLactose.\n"
           "10. DATE OF REVISION OF THE TEXT\n11/2025\n")
    two = one.replace("5 mg", "7.5 mg")
    sections = split_smpc_sections(one + two)
    assert sections["4.4"] == "Bradycardia 5 mg." and sections["smpc2:4.4"] == "Bradycardia 7.5 mg."
    assert sections["10"] == "11/2025"                       # the second SmPC no longer runs on inside it
    assert watched_changes(["smpc2:4.4", "smpc2:10", "10"]) == ["smpc2:4.4"]


def test_a_single_smpc_keeps_its_keys():
    from collectors.spc.sections import split_numbered, split_smpc_sections

    text = ("1. NAME OF THE MEDICINAL PRODUCT\nX 8 mg\n4. CLINICAL PARTICULARS\n4.3 Contraindications\nNone.\n"
            "10. DATE OF REVISION OF THE TEXT\n10/2026\n")
    assert split_smpc_sections(text) == split_numbered(text)


def test_us_old_format_precautions_are_read():
    xml = b"""<document xmlns="urn:hl7-org:v3"><effectiveTime value="20250501"/>
      <component><structuredBody>
        <component><section><code code="34071-1"/><text>Liver warning.</text></section></component>
        <component><section><code code="42232-9"/><text>General. Hepatic impairment.</text>
          <component><section><code code="42228-7"/><text>Pregnancy Category C.</text></section></component>
        </section></component>
      </structuredBody></component></document>"""
    sections, when = dailymed.parse_spl(xml)
    assert "Pregnancy Category C." in sections["us:precautions"]      # sub-sections stay inside it
    assert sections["us:warnings"] == "Liver warning." and when == date(2025, 5, 1)


class _Versioned:
    @staticmethod
    def listed_version(product):
        return (product.get("extra") or {}).get("v")


def _row(pid, v, checked=None, ref=False):
    return {"id": pid, "national_id": pid, "extra": {"v": v}, "checked_at": checked, "is_reference": ref}


def test_a_label_the_regulator_revised_is_read_first_and_an_unchanged_one_waits():
    from datetime import datetime, timedelta, timezone

    from collectors.spc.run import SpcStats, _turn, plan_reads

    lately = datetime.now(timezone.utc) - timedelta(days=3)
    long_ago = datetime.now(timezone.utc) - timedelta(days=40)
    ing = {"id": "i"}
    queue = [(_row("same", "3", lately), ing), (_row("old", "3", long_ago), ing),
             (_row("new", "5", lately), ing), (_row("ref", "3", lately, ref=True), ing),
             (_row("never", "1"), ing)]
    stats = SpcStats()
    got = plan_reads(_Versioned, queue, {"same": "3", "old": "3", "new": "4", "ref": "3"}, stats)
    got.sort(key=lambda pair: _turn(pair[0]))
    assert [p["id"] for p, _i in got] == ["ref", "new", "never", "old"]
    assert (stats.revised, stats.unchanged) == (1, 1)


def test_a_source_without_listed_versions_reads_every_label():
    from collectors.spc.run import SpcStats, plan_reads

    queue = [(_row("a", "1"), {"id": "i"})]
    assert plan_reads(object(), queue, {"a": "1"}, SpcStats()) == queue


def test_the_snapshot_keeps_the_regulator_version_and_follows_it_on_the_same_text():
    db, ctx = SpcDb(), FakeCtx()

    class Module(_Versioned):
        def snapshot(self, ctx, product):
            return Snapshot(sections={"4.4": "Texto."}, lang="es")

    product = dict(PRODUCT, extra={"v": "2026-10-01"})
    watch_product(db, ctx, Module(), "spc-cima", product, INGREDIENT)
    assert db.snapshots[-1]["regulator_version"] == "2026-10-01"
    watch_product(db, ctx, Module(), "spc-cima", dict(product, extra={"v": "2026-11-02"}), INGREDIENT)
    assert len(db.snapshots) == 1 and db.snapshots[-1]["regulator_version"] == "2026-11-02"
