"""Acceptance cases for collectors/matching.py, using the real seed watchlist (0003_seed_watchlist.sql).

The texts below are test copies written for these cases (plan, verification 4); they are not
regulator fixtures.
"""

from __future__ import annotations

import pytest

from collectors.core.memstore import MemoryStore
from collectors.matching import DocumentMatch, Matcher, Term, norm, normalise, similarity


@pytest.fixture(scope="module")
def matcher() -> Matcher:
    store = MemoryStore()
    store.load_seed()
    return Matcher(store.load_terms())


def ingredient_hits(hits):
    return [h for h in hits if h.term.ingredient_id]


def test_seed_loaded(matcher):
    langs = {c.term.lang for c in matcher.compiled if c.term.ingredient_id}
    assert {"en", "de", "fi", "sv", "nb", "ja", "ko", "ar"} <= langs
    assert any(c.term.is_class and c.term.term == "NSAR" for c in matcher.compiled)


def test_finnish_inflection_matches(matcher):
    text = "Lornoksikaamia sisältävien valmisteiden valmisteyhteenvetoa päivitetään."
    hits = ingredient_hits(matcher.match_text(text, "body", lang="fi"))
    assert hits
    h = hits[0]
    assert h.matched_text == "Lornoksikaamia"
    assert text[h.start:h.end] == "Lornoksikaamia"
    assert h.confidence == "high"


def test_japanese_inside_text(matcher):
    text = "【使用上の注意】本剤（ロルノキシカム錠4mg）を投与する場合は注意すること。"
    hits = ingredient_hits(matcher.match_text(text, "attachment", lang="ja"))
    assert hits
    assert text[hits[0].start:hits[0].end] == "ロルノキシカム"


def test_half_width_katakana_unifies(matcher):
    text = "ﾛﾙﾉｷｼｶﾑ錠"
    hits = ingredient_hits(matcher.match_text(text, "body", lang="ja"))
    assert hits and hits[0].matched_text == "ﾛﾙﾉｷｼｶﾑ"


def test_line_end_hyphenation_rejoined(matcher):
    text = "Patienten, die Lornoxi-\ncam einnehmen, sollten überwacht werden."
    hits = ingredient_hits(matcher.match_text(text, "attachment", lang="de"))
    assert hits
    h = hits[0]
    assert h.matched_text == "Lornoxi-\ncam"
    assert text[h.start:h.end] == "Lornoxi-\ncam"


@pytest.mark.parametrize("text,lang", [
    ("Tenoksikaami ja meloksikaami ovat oksikaameja.", "fi"),
    ("Meloxicam and tenoxicam tablets: new warning.", "en"),
    ("Piroxicam-haltige Arzneimittel", "de"),
])
def test_other_oxicams_never_match(matcher, text, lang):
    assert ingredient_hits(matcher.match_text(text, "body", lang=lang)) == []
    assert ingredient_hits(matcher.match_text(text, "attachment", lang=lang, ocr=True)) == []


def test_german_class_term_is_class_only(matcher):
    text = "Rote-Hand-Brief: Anwendung NSAR-haltiger Arzneimittel ab der 20. Schwangerschaftswoche"
    hits = matcher.match_text(text, "title", lang="de")
    dm = DocumentMatch(hits)
    assert hits and dm.class_only
    assert hits[0].matched_text == "NSAR"


def test_class_terms_stay_in_their_language(matcher):
    # "AINS" is a French class term (exact); "ainsi" must not match, nor "AINS" in an English text.
    assert matcher.match_text("Il est ainsi recommandé de surveiller.", "body", lang="fr") == []
    assert matcher.match_text("Les AINS exposent à un risque.", "body", lang="fr")
    assert matcher.match_text("The AINS committee met.", "body", lang="en") == []


def test_offsets_map_back_through_normalisation(matcher):
    text = "Die Lorno­xicam-Tabletten und ＬＯＲＮＯＸＩＣＡＭ   Pulver"
    hits = ingredient_hits(matcher.match_text(text, "body", lang="de"))
    found = {text[h.start:h.end] for h in hits}
    assert "Lorno­xicam" in found
    assert "ＬＯＲＮＯＸＩＣＡＭ" in found
    for h in hits:
        assert h.matched_text == text[h.start:h.end]
        assert h.matched_text in h.snippet or h.matched_text.replace("­", "") in h.snippet.replace("­", "")


def test_german_genitive_and_swedish(matcher):
    assert ingredient_hits(matcher.match_text("Anwendung des Lornoxicams", "body", lang="de"))
    assert ingredient_hits(matcher.match_text("Lornoxikam (Xefo) tabletter", "body", lang="sv"))


def test_brand_is_exact(matcher):
    hits = ingredient_hits(matcher.match_text("Xefo® 8 mg Filmtabletten", "title", lang="de"))
    assert any(h.term.kind == "brand" for h in hits)
    assert not any(h.term.kind == "brand" for h in matcher.match_text("Xefoxyl", "title", lang="de"))


def test_arabic_prefixes_and_tashkeel(matcher):
    text = "تحذير بشأن اللُّورنوكسيكام وأدوية أخرى"
    hits = ingredient_hits(matcher.match_text(text, "body", lang="ar"))
    assert hits
    assert "ورنوكسيكام" in hits[0].matched_text.replace("ُ", "").replace("ّ", "")


def test_ocr_fuzzy_is_possible_only(matcher):
    text = "Valmiste sisältää Lornoxicarn 8 mg"
    assert ingredient_hits(matcher.match_text(text, "attachment", lang="fi")) == []
    hits = ingredient_hits(matcher.match_text(text, "attachment", lang="fi", ocr=True))
    assert hits and all(h.confidence == "possible" for h in hits)
    assert not DocumentMatch(hits).has_high


def test_class_term_does_not_lift_a_possible_ingredient_hit(matcher):
    # An exact class term ("NSAR") next to an OCR near-miss of the ingredient: still no alert.
    text = "Hinweis zu NSAR. Das Präparat enthält Lornoxicarn 8 mg."
    hits = matcher.match_text(text, "attachment", lang="de", ocr=True)
    assert any(h.term.is_class and h.confidence == "high" for h in hits)
    assert ingredient_hits(hits) and all(h.confidence == "possible" for h in ingredient_hits(hits))
    dm = DocumentMatch(hits)
    assert not dm.class_only and not dm.has_high


def test_structured_fields_are_high(matcher):
    row = {"active_substance": "lornoxicam", "active_substances_in_scope_of_procedure": "lornoxicam"}
    hits = matcher.match_structured(row, ["active_substance"])
    assert hits and hits[0].field == "structured" and hits[0].confidence == "high"
    assert hits[0].path == "active_substance"


def test_class_word_never_inside_another_word():
    m = Matcher([Term(id="c1", term="oxicam", lang="en", class_id="cls")])
    assert m.match_text("tenoxicam", "body", lang="en") == []
    assert m.match_text("the oxicams as a class", "body", lang="en")


def test_normalise_offsets_are_monotonic():
    text = "Ångström ß Ｆｕｌｌ ｶﾞ ﬁne"
    nt = normalise(text)
    assert nt.text.startswith("angstrom ss full ガ fine")
    assert all(a <= b for a, b in zip(nt.starts, nt.starts[1:], strict=False))
    assert norm("Anti-inflammatoires NON stéroïdiens") == "anti-inflammatoires non steroidiens"


def test_similarity_bounds():
    assert similarity("lornoxicam", "lornoxicam") == 1.0
    assert similarity("lornoxicam", "meloxicam") < 0.55
