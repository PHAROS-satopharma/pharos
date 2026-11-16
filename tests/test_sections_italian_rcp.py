"""The layouts that left Italian RCPs (AIFA) without sections 4.3, 4.4 and 4.8 until 17 Nov 2026
(collectors/spc/sections.py, ``split_numbered``): a hyphen or bracket after the number ("4.1-Indicazioni",
"4.1) Indicazioni"), and a cross-reference to 4.9 at the start of a line inside 4.2. The texts are cut to the
headings and a line of each section, in the layout pdftotext gave for AIFA's own files (Levofloxacina Bioindustria,
Caravel, Paracetamolo Coop)."""

from __future__ import annotations

from collectors.spc.sections import missing_core, split_numbered

WATCHED = ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"]

_BODY = {
    "4.1": "Indicazioni terapeutiche", "4.2": "Posologia e modo di somministrazione", "4.3": "Controindicazioni",
    "4.4": "Avvertenze speciali e precauzioni di impiego",
    "4.5": "Interazioni con altri medicinali e altre forme di interazione",
    "4.6": "Fertilità, gravidanza e allattamento",
    "4.7": "Effetti sulla capacità di guidare veicoli e sull'uso di macchinari",
    "4.8": "Effetti indesiderati", "4.9": "Sovradosaggio",
}


def _rcp(sep: str, top_sep: str, cross_refs: dict[str, str] | None = None) -> str:
    lines = [f"1{top_sep}DENOMINAZIONE DEL MEDICINALE", "Medicinale 500 mg compresse",
             f"2{top_sep}COMPOSIZIONE QUALITATIVA E QUANTITATIVA", "Ogni compressa contiene 500 mg.",
             f"3{top_sep}FORMA FARMACEUTICA", "Compressa.", f"4{top_sep}INFORMAZIONI CLINICHE"]
    for key, heading in _BODY.items():
        lines += [f"{key}{sep}{heading}", f"Testo della sezione {key}."]
        if cross_refs and key in cross_refs:
            lines.append(cross_refs[key])
    lines += [f"5{top_sep}PROPRIETA' FARMACOLOGICHE", f"5.1{sep}Proprietà farmacodinamiche", "Analgesico.",
              f"10{top_sep}DATA DI REVISIONE DEL TESTO", "Marzo 2025"]
    return "\n".join(lines)


# Levofloxacina Bioindustria (040035): "4.1-Indicazioni", and cross-references closing a line ("4.4).").
HYPHEN = _rcp("-", "-", {"4.1": "pazienti a rischio (vedere paragrafo", "4.2": "4.4)."})
# Caravel (036339): "4) INFORMAZIONI CLINICHE", "4.1) Indicazioni terapeutiche".
BRACKET = _rcp(") ", ") ")
# Paracetamolo Coop (030350): "4.9 “Sovradosaggio”)." opens a line inside 4.2.
CROSS_REF = _rcp(". ", ". ", {"4.2": "Negli adulti la dose massima è di 3000 mg al giorno (vedere la sezione\n"
                                      "4.9 “Sovradosaggio”).\nIl medico deve valutare."})


def _check(text: str) -> dict[str, str]:
    s = split_numbered(text)
    assert missing_core(s) == [] and [k for k in WATCHED if k not in s] == []
    for key in WATCHED:
        assert s[key].startswith(f"Testo della sezione {key}."), (key, s[key][:60])
    return s


def test_a_hyphen_after_the_number_is_a_heading():
    s = _check(HYPHEN)
    assert s["4.2"].endswith("4.4).") and s["10"] == "Marzo 2025"


def test_a_bracket_after_the_number_is_a_heading():
    assert _check(BRACKET)["10"] == "Marzo 2025"


def test_a_cross_reference_to_4_9_inside_4_2_is_text():
    s = _check(CROSS_REF)
    assert "4.9 “Sovradosaggio”)." in s["4.2"] and "Il medico deve valutare." in s["4.2"]


def test_a_dash_written_in_a_dose_range_is_never_a_heading():
    # "7 -10 giorni" in a dosing table of 4.2 (Summaflox) is no section 7
    text = HYPHEN.replace("Testo della sezione 4.2.", "Testo della sezione 4.2.\n7 -10 giorni\n3 giorni")
    s = _check(text)
    assert "7 -10 giorni" in s["4.2"] and "7" not in s
