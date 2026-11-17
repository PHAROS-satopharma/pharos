"""The two layouts that left 55 Dutch SmPCs (CBG, mostly paracetamol suppositories) without sections 4.3, 4.4 and
4.8 until 17 Nov 2026 (collectors/spc/sections.py, ``split_numbered``). The texts are cut to the headings and a
line of each section, in the layout pdftotext gave for the CBG's own files (h24204, h57799)."""

from __future__ import annotations

from collectors.spc import sections as sections_module
from collectors.spc.sections import _split_numbered, eu_label_sections, missing_core, split_numbered

WATCHED = ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"]

# h24204 (Paracetamol HTP zetpil 500 mg): top-level headings in sentence case, never upper-case.
SENTENCE_CASE = """\
1     Naam van het geneesmiddel
Paracetamol HTP zetpil 500 mg, zetpillen
2     Kwalitatieve en kwantitatieve samenstelling
Elke zetpil bevat 500 mg paracetamol.
3     Farmaceutische vorm
Zetpil.
4     Klinische gegevens
4.1   Therapeutische indicaties
Voor de symptomatische behandeling van lichte tot matige pijn en/of koorts.
4.2   Dosering en wijze van toediening
De dosering is afhankelijk van het lichaamsgewicht.
4.3   Contra-indicaties
Overgevoeligheid voor de werkzame stof.
4.4   Speciale waarschuwingen en bijzondere voorzorgen bij gebruik
Niet langer dan noodzakelijk gebruiken.
4.5   Interacties met andere geneesmiddelen en andere vormen van interacties
Probenecide remt de glucuronidering.
4.6   Vruchtbaarheid, zwangerschap en borstvoeding
Paracetamol kan tijdens de zwangerschap worden gebruikt.
4.7   Beinvloeding van de rijvaardigheid en het vermogen om machines te bedienen
Geen of verwaarloosbare invloed.
4.8   Bijwerkingen
Zeer zelden overgevoeligheidsreacties.
4.9   Overdosering
Voor paracetamol is er een risico op vergiftiging.
5     Farmacologische eigenschappen
5.1   Farmacodynamische eigenschappen
Analgeticum en antipyreticum.
6     Farmaceutische gegevens
6.3   Houdbaarheid
3     jaar
6.5   Aard en inhoud van de verpakking
5     zetpillen in een PVC/PE zetpilstrip.
7     Houder van de vergunning voor het in de handel brengen
HTP Huisapotheek
8     Nummer van de vergunning voor het in de handel brengen
RVG 24204
9     Datum van eerste vergunning/hernieuwing van de vergunning
Datum van eerste verlening van de vergunning: 22 augustus 2000
10    Datum van herziening van de tekst
Laatste gedeeltelijke wijziging betreft rubriek 4.4: 3 april 2024
"""

# h57799 (Paracetamol Sanias 500 mg): upper-case headings, but the dosing table in 4.2 has rows that start with a
# number and hold no word ("6 – 9 ..."), and one of them was taken for heading 6.
DOSING_TABLE = """\
1.    NAAM VAN HET GENEESMIDDEL
Paracetamol Sanias 500 mg, zetpillen
4.    KLINISCHE GEGEVENS
4.1   Therapeutische indicaties
Symptomatische behandeling van pijn en koorts.
4.2   Dosering en wijze van toediening
Leeftijd (jaar)       Gewicht (kg)      Dosis (mg)      Aantal per dag
1 – 2                  10 - 12,5          120             3 - 4
6 – 9                  22 - 30            500             2 – 3
9 – 12                 30 – 40            500             3
12 – 15                40 - 55            1000            2 - 3
Zie rubriek 4.4 en 4.9).
4.3   Contra-indicaties
Overgevoeligheid voor de werkzame stof.
4.4   Bijzondere waarschuwingen en voorzorgen bij gebruik
Niet langer dan noodzakelijk gebruiken.
4.8   Bijwerkingen
Zeer zelden overgevoeligheidsreacties.
4.9   Overdosering
Voor paracetamol is er een risico op vergiftiging.
5.    FARMACOLOGISCHE EIGENSCHAPPEN
5.1   Farmacodynamische eigenschappen
Analgeticum.
10.   DATUM VAN HERZIENING VAN DE TEKST
Laatste herziening: februari 2025
"""


def test_sentence_case_top_headings_give_every_watched_section():
    sections = eu_label_sections(SENTENCE_CASE)
    assert missing_core(sections) == []
    assert [k for k in WATCHED if k in sections] == WATCHED
    assert sections["4.3"] == "Overgevoeligheid voor de werkzame stof."
    assert sections["4.9"] == "Voor paracetamol is er een risico op vergiftiging."
    assert sections["10"].startswith("Laatste gedeeltelijke wijziging")


def test_a_sentence_that_starts_with_a_number_is_not_a_heading():
    # "3 jaar" (6.3) and "5 zetpillen in een PVC/PE zetpilstrip." (6.5) stay body text.
    sections = split_numbered(SENTENCE_CASE)
    assert sections["6.3"] == "3     jaar"
    assert "zetpillen in een PVC/PE zetpilstrip." in sections["6.5"]
    assert "7" in sections and "10" in sections


def test_a_dosing_table_row_with_no_word_is_not_heading_6():
    sections = eu_label_sections(DOSING_TABLE)
    assert missing_core(sections) == []
    assert "6 – 9" in sections["4.2"] and "12 – 15" in sections["4.2"]
    assert sections["4.8"] == "Zeer zelden overgevoeligheidsreacties."
    assert sections["10"] == "Laatste herziening: februari 2025"


def _add_after(text: str, anchor: str, extra: str) -> str:
    assert text.count(anchor) == 1
    return text.replace(anchor, anchor + extra)


OVERDOSE = "Voor paracetamol is er een risico op vergiftiging.\n"


def test_a_label_that_split_before_splits_exactly_as_before():
    # An upper-case SmPC the strict rules split completely never reaches the lenient ones, and keeps a
    # sentence-case line starting with the next top-level number inside 4.9.
    text = _add_after(DOSING_TABLE, OVERDOSE, "5 Patienten met leverziekte\n")
    strict, _ = _split_numbered(text.splitlines(), lenient=False)
    assert missing_core(strict) == []
    assert split_numbered(text) == strict
    assert strict["4.9"].endswith("5 Patienten met leverziekte")


def test_a_wordless_row_after_the_core_sections_is_not_a_heading():
    # strict split: "5    10    20" in 4.8 once swallowed 4.9 and section 5
    text = _add_after(DOSING_TABLE, "Zeer zelden overgevoeligheidsreacties.\n", "5    10    20\n")
    sections = split_numbered(text)
    assert sections["4.8"].endswith("5    10    20")
    assert sections["4.9"] == "Voor paracetamol is er een risico op vergiftiging."
    assert sections["5"] == ""


def test_cover_text_above_heading_1_keeps_an_upper_case_file_strict():
    # "4.3- Contra-indicaties" sends the split to the lenient rules; the cover line must not make the file
    # sentence case there.
    text = "1 Zetpil bevat 500 mg paracetamol\n" + _add_after(DOSING_TABLE, OVERDOSE, "5 Patienten met leverziekte\n")
    text = text.replace("4.3   Contra-indicaties", "4.3- Contra-indicaties")
    # and with no later heading 5 to give way to, only the file's case keeps "5 Patienten …" out of the headings
    text = text.replace("5.    FARMACOLOGISCHE EIGENSCHAPPEN\n", "")
    strict, _ = _split_numbered(text.splitlines(), lenient=False)
    assert "4.3" not in strict
    sections = split_numbered(text)
    assert sections["1"] == "Paracetamol Sanias 500 mg, zetpillen"
    assert sections["4.3"] == "Overgevoeligheid voor de werkzame stof."
    assert sections["4.9"].endswith("5 Patienten met leverziekte")


def test_a_sentence_case_body_line_with_the_next_number_stays_in_its_section():
    text = _add_after(SENTENCE_CASE, OVERDOSE, "5 Patienten met leverziekte\nBehandel direct.\n")
    text = _add_after(text, "De dosering is afhankelijk van het lichaamsgewicht.\n", "5 Jaar en ouder\n")
    sections = split_numbered(text)
    assert missing_core(sections) == []
    assert sections["4.2"].endswith("5 Jaar en ouder")
    assert sections["4.9"].endswith("5 Patienten met leverziekte\nBehandel direct.")
    assert "Farmacologische eigenschappen" not in sections["5"]


def test_a_sentence_case_file_without_heading_1_or_3_still_splits():
    no_one = SENTENCE_CASE.replace("1     Naam van het geneesmiddel\nParacetamol HTP zetpil 500 mg, zetpillen\n", "")
    assert missing_core(split_numbered(no_one)) == []
    no_three = SENTENCE_CASE.replace("3     Farmaceutische vorm\nZetpil.\n", "")
    sections = split_numbered(no_three)
    assert missing_core(sections) == []
    assert sections["4.3"] == "Overgevoeligheid voor de werkzame stof."


def test_a_sentence_case_file_with_two_smpcs_is_cut_in_two():
    second = SENTENCE_CASE.replace("500 mg", "1000 mg").replace("RVG 24204", "RVG 24205")
    sections = eu_label_sections(SENTENCE_CASE + second)
    assert missing_core(sections) == [] and missing_core(sections, prefix="smpc2:") == []
    assert sections["10"] == "Laatste gedeeltelijke wijziging betreft rubriek 4.4: 3 april 2024"
    assert sections["smpc2:4.3"] == "Overgevoeligheid voor de werkzame stof."


def test_no_second_pass_when_no_lenient_rule_reads_any_line_differently(monkeypatch):
    calls = []
    real = sections_module._split_numbered

    def counting(lines, *, lenient):
        calls.append(lenient)
        return real(lines, lenient=lenient)

    monkeypatch.setattr(sections_module, "_split_numbered", counting)
    fragment = "4.    KLINISCHE GEGEVENS\n4.1   Therapeutische indicaties\nPijn.\n"
    assert missing_core(split_numbered(fragment)) == ["4.3", "4.4", "4.8"]
    assert calls == [False]
    calls.clear()
    split_numbered(SENTENCE_CASE)
    assert calls == [False, True]
