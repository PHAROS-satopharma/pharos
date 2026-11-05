"""UK label watch: the MHRA disclaimer is ticked, and only SPCs whose active substance is the
ingredient count as its products. Before this, the reader never got past the disclaimer. If it had,
the full-text search would have filed fluconazole SPCs (which mention lornoxicam among their
interactions) as lornoxicam products."""

from __future__ import annotations

from pathlib import Path

from collectors.spc import mhra

FIX = Path(__file__).parent / "fixtures" / "spc-mhra"
BASE = "https://products.mhra.gov.uk/search/?search={q}&page=1&doc=Spc&rerouteType=0"


def _html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_fluconazole_spcs_that_mention_lornoxicam_are_not_lornoxicam_products():
    html = _html("search_lornoxicam_agreed.html")
    assert len(mhra.parse_results(html, BASE.format(q="lornoxicam"))) == 4      # every hit, unfiltered
    assert mhra.parse_results(html, BASE.format(q="lornoxicam"), ["lornoxicam"]) == []


def test_naproxen_spcs_are_kept_with_their_licence_number():
    got = mhra.parse_results(_html("search_naproxen_agreed.html"), BASE.format(q="naproxen"), ["naproxen"])
    assert [p.national_id for p in got] == ["PL 00142/0278", "PL 52104/0019", "PL 53797/0034"]
    assert got[0].product_name == "NAPROXEN TABLETS BP 500MG"
    assert got[0].url.startswith("https://mhraproducts4853.blob.core.windows.net/docs/")


def test_a_combination_product_counts_for_each_of_its_substances():
    assert mhra.names_ingredient(mhra.substances("Active substances: FLUCONAZOLE, CLOTRIMAZOLE MICRONISED"),
                                 ["clotrimazole"])
    assert not mhra.names_ingredient(mhra.substances("Active substances: MELOXICAM"), ["oxicam"])


class _Page:
    def __init__(self, disclaimer: bool, stays: bool = False) -> None:
        self.disclaimer, self.stays, self.actions = disclaimer, stays, []

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.actions.append(("wait", selector, state))
        if state == "detached" and self.stays:
            raise TimeoutError("still attached")

    def query_selector(self, selector):
        return object() if self.disclaimer and selector == mhra.AGREE else None

    def check(self, selector):
        self.actions.append(("check", selector))

    def click(self, selector):
        self.actions.append(("click", selector))


def test_the_disclaimer_is_ticked_and_agreed_when_shown():
    page = _Page(disclaimer=True)
    mhra.accept_disclaimer(page)
    assert ("check", "#agree-checkbox") in page.actions
    assert ("click", "form:has(#agree-checkbox) button[type=submit]") in page.actions


def test_nothing_is_clicked_when_no_disclaimer_is_shown():
    page = _Page(disclaimer=False)
    mhra.accept_disclaimer(page)
    assert [a for a in page.actions if a[0] != "wait"] == []


def test_discover_passes_the_disclaimer_step_to_the_browser():
    calls = []

    class _Ctx:
        def browser_get(self, url, **kw):
            calls.append(kw)
            from collectors.core.context import Fetched
            body = _html("search_naproxen_agreed.html") if not calls[1:] else "<html></html>"
            return Fetched(200, url, body.encode(), "text/html; charset=utf-8")

    got = mhra.discover(_Ctx(), {"inn_en": "naproxen", "terms": {"en": ["naproxen"]}})
    assert len(got) == 3
    assert calls[0]["before_wait"] is mhra.accept_disclaimer


def test_a_disclaimer_that_stays_after_agree_is_an_error_not_no_results():
    import pytest
    with pytest.raises(mhra.DisclaimerNotAccepted):
        mhra.accept_disclaimer(_Page(disclaimer=True, stays=True))


def test_discover_logs_the_hits_it_saw(caplog):
    import logging

    class _Ctx:
        n = 0

        def browser_get(self, url, **kw):
            from collectors.core.context import Fetched
            self.n += 1
            body = _html("search_lornoxicam_agreed.html") if self.n == 1 else "<html></html>"
            return Fetched(200, url, body.encode(), "text/html; charset=utf-8")

    with caplog.at_level(logging.INFO, logger="collectors.spc.mhra"):
        assert mhra.discover(_Ctx(), {"inn_en": "lornoxicam", "terms": {"en": ["lornoxicam"]}}) == []
    assert "4 search hit(s), 0 with it as an active substance" in caplog.text
