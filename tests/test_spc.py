"""PHAROS — SPC / label watch (A2): section splitting, diffs, discovery from real fixtures, and the
snapshot → change → issue flow of ``collectors.spc.run`` against an in-memory database.

Fixtures (tests/fixtures/spc-*) were saved from the regulators on 4 Nov 2026. Section texts stay in
the label's own language; nothing is translated.
"""

from __future__ import annotations

import json
from datetime import date

from collectors.spc import bdpm, cima, mhra, pmda_pi
from collectors.spc.common import Snapshot, terms_for
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
    assert p.extra["ft_date"] == "2023-10-16"
    assert p.extra["ft_html"] == "https://cima.aemps.es/cima/dochtml/ft/78274/FT_78274.html"


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


def test_bdpm_match_and_products():
    compo = [["60001234", "comprimé", "0001", "LORNOXICAM", "8 mg", "un comprimé", "SA", "1"],
             ["60001234", "comprimé", "0002", "LACTOSE", "", "", "FT", "2"],
             ["60009999", "comprimé", "0003", "PARACÉTAMOL", "", "", "SA", "1"],
             ["60005555", "comprimé", "0004", "LORNOXICAM", "", "", "XX", "1"]]
    assert bdpm.match_cis(compo, ["lornoxicam"]) == {"60001234"}
    cis = [["60001234", "LORNOXICAM 8 mg, comprimé", "comprimé", "orale", "Autorisation active",
            "Procédure nationale", "Commercialisée", "01/01/2010", "", "", " LABO X"],
           ["60007777", "AUTRE", "comprimé", "orale", "Autorisation abrogée", "Procédure nationale",
            "Non commercialisée", "01/01/2010", "", "", "LABO Y"]]
    got = bdpm.products_from(cis, {"60001234", "60007777"})
    assert [p.national_id for p in got] == ["60001234"]
    assert got[0].product_name == "LORNOXICAM 8 mg, comprimé" and got[0].mah == "LABO X"


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


def test_watch_product_without_archived_texts_compares_hashes():
    db, ctx = SpcDb(), FakeCtx()
    module = _Module(_snap("Texto A."), _snap("Texto B."))
    watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    ctx.archiver.objects.clear()                       # previous texts unreadable
    issue = watch_product(db, ctx, module, "spc-cima", PRODUCT, INGREDIENT)
    assert issue is not None
    assert db.changes[0]["s"] == ["4.4"]
    assert db.changes[0]["d"][0]["before"] is None
