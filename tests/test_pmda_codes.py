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
