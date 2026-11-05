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
from collectors.spc import bdpm, cima, ema_epar, mhra, pmda_pi
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
    ing = {"inn_en": "lornoxicam", "terms": {"fr": ["LORNOXICAM"]}}
    with pytest.raises(FetchError):
        bdpm.discover(FakeCtx(), ing)                                # 404 for the COMPO file
    compo = "60001234\tcomprimé\t0001\tLORNOXICAM\t8 mg\tun comprimé\tSA\t1\n".encode()
    cis = ("60001234\tLORNOXICAM 8 mg, comprimé\tcomprimé\torale\tAutorisation active\t"
           "Procédure nationale\tCommercialisée\t01/01/2010\t\t\tLABO X\tNon\n").encode()
    ctx = FakeCtx({bdpm.COMPO_URL: compo, bdpm.CIS_URL: cis})
    assert [p.national_id for p in bdpm.discover(ctx, ing)] == ["60001234"]


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
