"""Japan's label watch finds an ingredient's products from its Japanese code term on the
Ingredients page. Before this, lornoxicam had no stored code, so Japan watched nothing for it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from collectors.spc import pmda_pi

FIXTURE = Path(__file__).parent / "fixtures" / "spc-pmda" / "general_list_1149036.html"


class _Db:
    def __init__(self, terms: list[str], links: list[list[str]] | None = None) -> None:
        self.terms, self.links = terms, links or []

    def fetchall(self, sql, params=None):
        if sql is pmda_pi.SQL_TERM_CODES:
            return [{"term": t} for t in self.terms]
        if sql is pmda_pi.SQL_CODES:
            return [{"links": x} for x in self.links]
        raise AssertionError(sql)


ING = {"id": "ing-1", "inn_en": "lornoxicam"}


def test_a_japanese_code_term_gives_the_general_code(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ctx = SimpleNamespace(db=_Db(["1149036"]))
    assert pmda_pi.general_codes(ctx, ING) == ["1149036"]


def test_a_full_yj_code_is_cut_to_its_general_code_and_junk_is_ignored(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ctx = SimpleNamespace(db=_Db(["1149036f1025", "M01AC05", "12"],
                                 [["https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/1149036"]]))
    assert pmda_pi.general_codes(ctx, ING) == ["1149036"]


def test_lornoxicam_list_has_both_marketed_products():
    html = FIXTURE.read_text(encoding="utf-8")
    products = pmda_pi.parse_general_list(
        html, "https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/1149036")
    assert {p.national_id for p in products} == {"400059_1149036F1025", "270139_1149036F1033"}
    assert any(p.product_name.startswith("ロルカム錠") for p in products)


# A revision notice lists several ingredients, so its GeneralList links reach every ingredient matched to
# it. Such a code is kept only when the page's 一般名 names the ingredient.

LIST_2190417 = Path(__file__).parent / "fixtures" / "spc-pmda" / "general_list_2190417.html"
_REV = "https://www.pmda.go.jp/PmdaSearch/iyakuDetail/GeneralList/{}"


class _Ctx:
    def __init__(self, db, pages: dict[str, Path]) -> None:
        self.db, self.pages, self.asked = db, pages, []

    def get(self, url, **kw):
        from collectors.core.models import Fetched

        self.asked.append(url)
        page = self.pages.get(url)
        if page is None:
            return Fetched(404, url, b"", "text/html")
        return Fetched(200, url, page.read_bytes(), "text/html; charset=utf-8")


def test_the_general_name_is_read_from_the_page():
    assert pmda_pi.general_name(LIST_2190417.read_text(encoding="utf-8")) == "イブプロフェン Ｌ－リシン"
    assert pmda_pi.general_name(FIXTURE.read_text(encoding="utf-8")) == "ロルノキシカム"


def test_a_revision_notice_code_for_another_ingredient_is_not_watched(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ivabradine = {"id": "ing-2", "inn_en": "ivabradine", "terms": {"ja": ["イバブラジン"]}}
    ctx = _Ctx(_Db([], [[_REV.format("2190417")]]), {_REV.format("2190417"): LIST_2190417})
    assert pmda_pi.discover(ctx, ivabradine) == []
    assert ctx.asked == [_REV.format("2190417")]


def test_a_revision_notice_code_whose_general_name_matches_is_watched(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ibuprofen = {"id": "ing-3", "inn_en": "ibuprofen", "terms": {"ja": ["イブプロフェン"]}}
    ctx = _Ctx(_Db([], [[_REV.format("2190417")]]), {_REV.format("2190417"): LIST_2190417})
    got = pmda_pi.discover(ctx, ibuprofen)
    assert got and all(p.country_code == "JP" for p in got)


def test_a_revision_notice_code_is_not_read_without_a_japanese_name(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ibuprofen = {"id": "ing-3", "inn_en": "ibuprofen", "terms": {}}
    ctx = _Ctx(_Db([], [[_REV.format("2190417")]]), {_REV.format("2190417"): LIST_2190417})
    assert pmda_pi.discover(ctx, ibuprofen) == [] and ctx.asked == []


def test_a_code_from_the_ingredients_page_is_trusted_without_a_name_check(monkeypatch):
    monkeypatch.delenv("SPC_PMDA_GENERAL_CODES", raising=False)
    ctx = _Ctx(_Db(["1149036"], [[_REV.format("1149036")]]), {_REV.format("1149036"): FIXTURE})
    got = pmda_pi.discover(ctx, ING)                         # lornoxicam, no Japanese name stored
    assert {p.national_id for p in got} == {"400059_1149036F1025", "270139_1149036F1033"}
