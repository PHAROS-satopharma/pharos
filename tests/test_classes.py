"""Drug classes from the ATC code (collectors/classes.py), on WHO's and Wikidata's real answers saved on
6 November 2026 (tests/fixtures/atc-classes)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from collectors import classes as c
from collectors.core.memstore import MemoryStore
from collectors.matching import DocumentMatch, Matcher

FIX = Path(__file__).parent / "fixtures" / "atc-classes"


class SavedWeb:
    """Answers each request the code makes with the saved response; records what was asked."""

    def __init__(self, fail: str | None = None) -> None:
        self.asked: list[str] = []
        self.fail = fail

    def __call__(self, url: str, params: dict) -> bytes:
        if self.fail and self.fail in url:
            raise httpx.ConnectError("no answer")
        if url == c.WHO_URL:
            assert params == {"code": params["code"], "showdescription": "no"}
            self.asked.append(f"who {params['code']}")
            return (FIX / f"who-{params['code']}.html").read_bytes()
        if url == c.API_URL:
            assert params["srsearch"] == "Oxicams haswbstatement:P31=Q2585617"
            self.asked.append("search Oxicams")
            return (FIX / "wikidata-search-Oxicams.json").read_bytes()
        assert url == c.SPARQL_URL and params["format"] == "json"
        q = params["query"]
        for code in ("J01MA", "M01AC"):
            if q == c.query_by_atc(code):
                self.asked.append(f"wikidata {code}")
                return (FIX / f"wikidata-atc-{code}.json").read_bytes()
        assert q == c.query_by_items(["Q1143640"])
        self.asked.append("wikidata Q1143640")
        return (FIX / "wikidata-items-Q1143640.json").read_bytes()


def words(built: c.BuiltClass) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t in built.terms:
        out.setdefault(t["lang"], []).append(t["term"])
    return out


def test_level4_is_the_first_five_characters():
    assert c.level4("J01MA12") == "J01MA"
    assert c.level4(" m01ac05 ") == "M01AC"
    assert c.level4("J01M") is None
    assert c.level4(None) is None


def test_fluoroquinolones_from_the_atc_code_on_wikidata():
    web = SavedWeb()
    built = c.build_class(web, "J01MA")
    assert (built.code, built.name_en, built.wikidata_qid) == ("J01MA", "Fluoroquinolones", "Q28801726")
    w = words(built)
    assert sorted(w) == sorted(["en", "de", "fr", "it", "es", "nl", "da", "nb", "sv", "fi", "ko", "ar"])
    # singular and plural alias collapse into one stem; the misspelt aliases stay (notices misspell too)
    assert w["en"] == ["fluoroquinolone", "fluorquinolone", "fluroquinolone"]
    assert "Fluorchinolon" in w["de"]                  # from "Fluorchinolonantibiotikum"
    assert w["it"] == ["Fluorochinolon"]               # "Fluorochinoloni" → finds -one and -oni
    assert w["fi"] == ["Fluorokinolon"]                # "Fluorokinolonit"
    assert w["nb"] == ["Fluorokinolon"]                # "Fluorokinoloner"
    assert w["nl"] == ["fluorchinolon", "fluoroquinolone"]
    modes = {t["lang"]: t["mode"] for t in built.terms}
    assert modes["ko"] == "substring" and modes["en"] == "stem" and modes["ar"] == "stem"
    assert {t["source"] for t in built.terms} == {"wikidata"}
    assert web.asked == ["who J01MA", "wikidata J01MA"]  # an item carries the code: no search


def test_oxicams_have_no_atc_item_and_are_found_by_name_among_drug_classes():
    web = SavedWeb()
    built = c.build_class(web, "M01AC")
    assert (built.name_en, built.wikidata_qid) == ("Oxicams", "Q1143640")
    assert web.asked == ["who M01AC", "wikidata M01AC", "search Oxicams", "wikidata Q1143640"]
    w = words(built)
    assert w["en"] == ["oxicam"] and w["de"] == ["Oxicam"] and w["ja"] == ["オキシカム"]
    assert {t["mode"] for t in built.terms if t["lang"] == "ja"} == {"substring"}


def test_the_class_words_find_the_class_and_never_the_ingredient():
    built = c.build_class(SavedWeb(), "J01MA")
    terms = [c.Term(id=f"ct{k}", term=t["term"], lang=t["lang"], mode=t["mode"], class_id="fq", kind="class")
             for k, t in enumerate(built.terms)]
    m = Matcher(terms)
    sv = m.match_text("Information om fluorokinoloner och risk för senskador", "title", lang="sv")
    de = m.match_text("Rote-Hand-Brief zu Fluorchinolonen: Einschränkungen der Anwendung", "title", lang="de")
    fi = m.match_text("Fluorokinolonien käytön rajoitukset", "title", lang="fi")
    en = m.match_text("Fluoroquinolone antibiotics: reminder of the risk of disabling side effects", "title", lang="en")
    assert [h.matched_text for h in sv] == ["fluorokinoloner"]
    assert [h.matched_text for h in de] == ["Fluorchinolonen"]
    assert [h.matched_text for h in fi] == ["Fluorokinolonien"]
    assert [h.matched_text for h in en] == ["Fluoroquinolone"]
    assert DocumentMatch(en).class_only
    # a class word only applies in its own language, and never inside the ingredient's name
    assert m.match_text("fluorokinoloner", "title", lang="da") == []
    assert m.match_text("Levofloxacin 500 mg", "title", lang="en") == []
    oxi = c.build_class(SavedWeb(), "M01AC")
    m2 = Matcher([c.Term(id=f"o{k}", term=t["term"], lang=t["lang"], mode=t["mode"], class_id="ox", kind="class")
                  for k, t in enumerate(oxi.terms)])
    assert m2.match_text("Lornoxicam and meloxicam tablets", "title", lang="en") == []
    assert [h.matched_text for h in m2.match_text("Oxicams: skin reactions", "title", lang="en")] == ["Oxicams"]


@pytest.mark.parametrize("value,lang,ok", [
    ("fluoroquinolone", "en", True),
    ("J01MA", "en", False),                       # a code
    ("quinolone (antibiotic)", "en", False),      # punctuation
    ("3rd generation cephalosporin", "en", False),  # digits
    ("drug used in the treatment of infections", "en", False),  # a phrase
    ("abc", "en", False),                         # too short
    ("キノロン", "ja", True),
])
def test_junk_is_dropped(value, lang, ok):
    assert c.usable(value, lang) is ok


@pytest.mark.parametrize("value,lang,expected", [
    ("fluoroquinolones", "en", "fluoroquinolone"),
    ("glass", "en", "glass"),
    ("Fluorochinoloni", "it", "Fluorochinolon"),
    ("Fluorchinolone", "de", "Fluorchinolon"),
    ("fluorchinolonen", "nl", "fluorchinolon"),
    ("Fluorokinoloner", "sv", "Fluorokinolon"),
    ("Fluorokinolonit", "fi", "Fluorokinolon"),
    ("non-steroidal anti-inflammatory drugs", "en", "non-steroidal anti-inflammatory drug"),
    ("oxicams", "en", "oxicam"),
    ("NSAIDs", "en", "NSAID"),
    ("bólgueyðandi gigtarlyf", "is", "bólgueyðandi gigtarlyf"),
])
def test_plurals_are_cut_back_to_a_stem(value, lang, expected):
    assert c.stem(value, lang) == expected


def test_other_and_combination_groups_give_no_who_word():
    assert c._WHO_NOT_A_WORD.search("Other quinolones")
    assert c._WHO_NOT_A_WORD.search("Combinations of penicillins")
    assert not c._WHO_NOT_A_WORD.search("Fluoroquinolones")


def store_with(*ingredients: tuple[str, str, str]) -> MemoryStore:
    s = MemoryStore()
    for iid, inn, atc in ingredients:
        s.ingredient[iid] = {"inn_en": inn, "atc_code": atc, "active": True}
    return s


def test_run_makes_each_class_once_and_links_every_ingredient_of_the_group():
    s = store_with(("levo", "levofloxacin", "J01MA12"), ("cipro", "ciprofloxacin", "J01MA02"),
                   ("x", "no group", "J01"))
    web = SavedWeb()
    out = c.run(s, web)
    cid = s.drug_class_id("J01MA")
    assert out.created == ["J01MA Fluoroquinolones"] and not out.failed
    assert sorted(out.linked) == ["ciprofloxacin → J01MA", "levofloxacin → J01MA"]
    assert sorted(i for i, k in s.ingredient_class if k == cid) == ["cipro", "levo"]
    assert web.asked.count("who J01MA") == 1
    assert s.drug_class[cid]["origin"] == "atc" and s.drug_class[cid]["wikidata_qid"] == "Q28801726"
    # every new class word is due for the check of the past
    class_terms = [t for t in s.terms if t.class_id == cid]
    assert len(class_terms) == 17 and all(s._due(t.id) for t in class_terms)
    assert set(s.rematch_due_terms()[1]) == {t.id for t in class_terms}
    # the next day: nothing to make, nothing asked
    web2 = SavedWeb()
    again = c.run(s, web2)
    assert again.created == [] and again.linked == [] and web2.asked == []


def test_an_existing_class_is_never_changed_only_linked():
    s = store_with(("levo", "levofloxacin", "J01MA12"))
    s.drug_class["hand"] = {"code": "J01MA", "name_en": "Fluoroquinolones", "origin": "hand", "wikidata_qid": None}
    web = SavedWeb()
    out = c.run(s, web)
    assert out.created == [] and out.linked == ["levofloxacin → J01MA"]
    assert ("levo", "hand") in s.ingredient_class and web.asked == []
    assert [t for t in s.terms if t.class_id == "hand"] == []


def test_lornoxicam_keeps_nsaid_and_gains_oxicams():
    s = MemoryStore()
    ing, nsaid = s.load_seed()
    c.run(s, SavedWeb())
    oxi = s.drug_class_id("M01AC")
    assert {k for i, k in s.ingredient_class if i == ing} == {nsaid, oxi}
    assert s.drug_class[nsaid]["code"] == "NSAID"


def test_a_source_that_does_not_answer_makes_nothing_and_is_tried_again():
    s = store_with(("levo", "levofloxacin", "J01MA12"))
    out = c.run(s, SavedWeb(fail="wikidata"))
    assert out.failed == ["levofloxacin (J01MA)"] and out.created == [] and out.linked == []
    assert s.drug_class == {} and s.ingredient_class == []
    out = c.run(s, SavedWeb())
    assert out.created == ["J01MA Fluoroquinolones"]


def test_dry_run_writes_nothing():
    s = store_with(("levo", "levofloxacin", "J01MA12"))
    out = c.run(s, SavedWeb(), dry_run=True)
    assert out.created == ["J01MA Fluoroquinolones"] and out.linked == ["levofloxacin → J01MA"]
    assert s.drug_class == {} and s.ingredient_class == [] and s.terms == []


def test_queries_refuse_anything_but_a_code_or_an_item_id():
    with pytest.raises(ValueError):
        c.query_by_atc('J01MA" . ?x ?y ?z')
    with pytest.raises(ValueError):
        c.query_by_items(["Q1 }"])
