"""Our label against an originator's label change (Phase 11, migration 0043): the Python port of the gap check
that used to run in the browser (``web/src/lib/labelGap.ts`` at 1cc4122). Every case of its vitest file is here,
then the shape of the gap the collector stores (``label_gap.gap``)."""

from __future__ import annotations

from collectors.labels import gap

LEAFLET = """SUMMARY OF PRODUCT CHARACTERISTICS
1. NAME OF THE MEDICINAL PRODUCT
Lornox 8 mg film-coated tablets
4. CLINICAL PARTICULARS
4.1 Therapeutic indications
Short-term relief of acute mild to moderate pain.
4.4 Special warnings and precautions for use
Use with caution in patients with renal impairment.
1. Monitor renal function in the elderly.
4.8 Undesirable effects
Nausea, dyspepsia and abdominal pain are common.
4.8.1 Tabulated list
Headache is uncommon.
5. PHARMACOLOGICAL PROPERTIES
5.1 Pharmacodynamic properties
NSAID."""


# ───────────────────────────── the cases of labelGap.test.ts ─────────────────────────────

def test_split_sections_finds_the_numbered_sections_and_keeps_lists_and_third_level_headings_inside():
    s = gap.split_sections(LEAFLET)
    # "4" and "5" are headings with no text of their own before 4.1 and 5.1, so they are left out.
    assert list(s) == ["1", "4.1", "4.4", "4.8", "5.1"]
    assert s["4.4"] == "Use with caution in patients with renal impairment. 1. Monitor renal function in the elderly."
    assert "Headache is uncommon." in s["4.8"]


def test_added_sentences_are_the_ones_the_originator_added():
    assert gap.added_sentences(
        "Use with caution in renal impairment.",
        "Use with caution in renal impairment. Cases of acute kidney injury have been reported.",
    ) == ["Cases of acute kidney injury have been reported."]


def test_compare_with_ours_says_covered_partly_or_missing():
    ours = ("Use with caution in patients with renal impairment. "
            "Cases of acute kidney injury have been reported rarely.")
    covered, partly, missing = gap.compare_with_ours([
        "Cases of acute kidney injury have been reported.",
        "Use with caution in renal impairment and hepatic failure.",
        "Drug reaction with eosinophilia and systemic symptoms (DRESS) can occur.",
    ], ours)
    assert covered["status"] == "covered"
    assert partly["status"] == "partly"
    assert missing["status"] == "missing"
    assert missing["closest"] is None
    assert covered["closest"] == "Cases of acute kidney injury have been reported rarely."
    assert 0 <= missing["score"] < 0.4 <= partly["score"] < 0.75 <= covered["score"] <= 1


def test_eu_section_maps_us_and_japanese_sections_to_the_smpc_section():
    assert gap.eu_section("us:adverse_reactions") == "4.8"
    assert gap.eu_section("ja:2") == "4.3"
    assert gap.eu_section("4.4") == "4.4"
    assert gap.eu_section("4.2.1") == "4.2"
    assert gap.eu_section("us:unknown") is None
    assert gap.eu_section("ja:revision") is None


def test_same_language_treats_en_and_en_gb_as_one():
    assert gap.same_language("en", "en-GB")
    assert not gap.same_language("en", "fr")
    assert not gap.same_language(None, "en")
    assert not gap.same_language("", "en")


# ───────────────────────────── the helpers ─────────────────────────────

def test_normalize_joins_pdf_hyphenation_and_squeezes_space():
    assert gap.normalize("renal impair-\nment  here") == "renal impairment here"
    assert gap.normalize("　a　 b ") == "a b"


def test_sentences_drop_headings_and_bullets_and_split_japanese_full_stops():
    assert gap.sentences("4.4 Warnings\nUse with caution in renal impairment; monitor renal function. • Short.") == [
        "4.4 Warnings Use with caution in renal impairment;", "monitor renal function."]
    assert gap.sentences("重篤な肝障害があらわれることがあるので観察を十分に行うこと。異常が認められた場合には投与を中止すること。") == [
        "重篤な肝障害があらわれることがあるので観察を十分に行うこと。", "異常が認められた場合には投与を中止すること。"]


def test_content_words_are_letters_only_four_or_more_without_common_words_and_plural_s():
    assert gap.content_words("The patients' kidneys: 3 cases of acute injury were reported.") == {
        "kidney", "case", "acute", "injury", "reported"}
    assert gap.content_words("Weakness") == {"weakness"}     # -ss is not a plural
    assert gap.content_words("dyspepsia, nausea") == {"dyspepsia", "nausea"}


# ───────────────────────────── the gap the collector stores ─────────────────────────────

DIFF = [
    {"section": "4.4", "before": "Use with caution in renal impairment.",
     "after": "Use with caution in renal impairment. Cases of acute kidney injury have been reported.",
     "changes": [{"op": "insert", "before": "", "after": "Cases of acute kidney injury have been reported."}]},
    {"section": "4.8", "before": "Nausea is common.",
     "after": "Nausea is common. Severe cutaneous adverse reactions including DRESS have been reported.",
     "changes": []},
    {"section": "10", "before": "May 2026", "after": "October 2026", "changes": []},
]
OURS = {"4.4": "Use with caution in patients with renal impairment. Cases of acute kidney injury have been reported rarely.",
        "4.8": "Nausea and dyspepsia are common."}


def test_label_gap_compares_each_watched_section_with_ours_and_counts():
    g = gap.label_gap(DIFF, OURS, "en", "en-GB")
    assert g["lang_match"] is True and g["our_lang"] == "en" and g["their_lang"] == "en-GB"
    assert [s["section"] for s in g["sections"]] == ["4.4", "4.8"]       # section 10 has no SmPC counterpart
    s44, s48 = g["sections"]
    assert s44["our_section"] == "4.4" and s44["our_text"] is True
    assert [a["status"] for a in s44["added"]] == ["covered"]
    assert s44["added"][0]["closest"] == "Cases of acute kidney injury have been reported rarely."
    assert [a["status"] for a in s48["added"]] == ["missing"]
    assert (s44["covered"], s44["partly"], s44["missing"]) == (1, 0, 0)
    assert (g["covered"], g["partly"], g["missing"]) == (1, 0, 1)


def test_label_gap_marks_a_section_our_label_lacks_as_missing():
    g = gap.label_gap(DIFF, {"4.4": OURS["4.4"]}, "en", "en")
    s48 = g["sections"][1]
    assert s48["our_text"] is False
    assert [a["status"] for a in s48["added"]] == ["missing"] and s48["added"][0]["closest"] is None


def test_label_gap_maps_a_us_label_onto_our_smpc_sections():
    diff = [{"section": "us:warnings_and_precautions", "before": "",
             "after": "Cases of acute kidney injury have been reported.", "changes": []}]
    g = gap.label_gap(diff, OURS, "en", "en")
    assert g["sections"][0]["section"] == "us:warnings_and_precautions"
    assert g["sections"][0]["our_section"] == "4.4"
    assert g["sections"][0]["added"][0]["status"] == "covered"


def test_label_gap_never_compares_across_languages():
    g = gap.label_gap(DIFF, OURS, "en", "es")
    assert g["lang_match"] is False and g["sections"] == []
    assert (g["covered"], g["partly"], g["missing"]) == (0, 0, 0)
    assert g["our_lang"] == "en" and g["their_lang"] == "es"


def test_label_gap_with_nothing_added_lists_the_section_with_no_sentences():
    diff = [{"section": "4.4", "before": "Use with caution in renal impairment. Monitor the patient.",
             "after": "Use with caution in renal impairment.", "changes": []}]
    g = gap.label_gap(diff, OURS, "en", "en")
    assert g["sections"][0]["added"] == [] and g["missing"] == 0


def test_label_gap_is_plain_json():
    import json

    g = gap.label_gap(DIFF, OURS, "en", "en")
    assert json.loads(json.dumps(g)) == g
