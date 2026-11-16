"""The two layouts that left 55 Dutch SmPCs (CBG, mostly paracetamol suppositories) without sections 4.3, 4.4 and
4.8 until 17 Nov 2026 (collectors/spc/sections.py, ``split_numbered``). The texts are cut to the headings and a
line of each section, in the layout pdftotext gave for the CBG's own files (h24204, h57799)."""

from __future__ import annotations

from collectors.spc.sections import eu_label_sections, missing_core, split_numbered

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


def test_a_label_that_split_before_splits_exactly_as_before():
    # The lenient rules run only when the strict split lacks 4.3, 4.4 or 4.8: an upper-case SmPC whose body has
    # a sentence-case line starting with the next top-level number keeps it inside 4.9.
    text = DOSING_TABLE.replace("1 – 2  ", "").replace("6 – 9  ", "").replace("9 – 12 ", "").replace("12 – 15", "")
    text = text.replace("Voor paracetamol is er een risico op vergiftiging.\n",
                        "Voor paracetamol is er een risico op vergiftiging.\n5 Patienten met leverziekte\n")
    sections = split_numbered(text)
    assert sections["4.9"].endswith("5 Patienten met leverziekte")
