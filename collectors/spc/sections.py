"""PHAROS — split a product label (SmPC / US PI / Japanese 添付文書) into numbered sections.

Section keys are language-neutral where the label format is:

* EU/UK/CH SmPC (QRD template, every EU language): ``"4.3"``, ``"4.4"``, ``"4.8"``, ``"10"`` …
  Headings are recognised by their number at the start of a line ("4.4 Advertencias y
  precauciones especiales de empleo", "4.4. Mises en garde…", "4.8 Undesirable effects"); the
  heading words are never translated or compared, so every language splits the same way.
* US PI (DailyMed SPL, by LOINC section code): ``"us:boxed_warning"``, ``"us:recent_major_changes"``,
  ``"us:contraindications"``, ``"us:warnings_and_precautions"``, ``"us:warnings"``, ``"us:precautions"``,
  ``"us:adverse_reactions"``, ``"us:drug_interactions"``, ``"us:specific_populations"``, ``"us:overdosage"``.
  A section's text holds its sub-sections: the old-format PRECAUTIONS (42232-9, before 2006 and on many generics)
  holds pregnancy, nursing, paediatric and geriatric use; an OTC label's Warnings (34071-1) holds "Do not use",
  "Ask a doctor" and "Stop use". Before 7 Nov 2026 PRECAUTIONS was not read at all.
* An EPAR product-information PDF holds one SmPC per strength or form: the second and later SmPCs are keyed
  ``"smpc2:4.4"`` … (``split_smpcs``); they are watched like the first.
* Japan (new-format 添付文書, 2019+): every numbered heading 1–26 is a boundary (``"ja:3"`` 組成・性状,
  ``"ja:5"`` 効能又は効果に関連する注意 … so their text never runs on inside the section before);
  watched are ``"ja:1"`` 警告, ``"ja:2"`` 禁忌, ``"ja:8"`` 重要な基本的注意,
  ``"ja:9"`` 特定の背景を有する患者に関する注意, ``"ja:10"`` 相互作用, ``"ja:11"`` 副作用,
  ``"ja:13"`` 過量投与. Old format (before 2019): 【警告】→ ja:1, 【禁忌】【原則禁忌】→ ja:2 and the
  whole 【使用上の注意】 block (慎重投与, 重要な基本的注意, 相互作用, 副作用 … numbered inside it) →
  ``"ja:precautions"``, which is watched; the other 【】 headings (【組成・性状】【効能・効果】
  【用法・用量】【薬物動態】 …) end the section before them and are not watched.

* Korea (nedrug XML, ``collectors/spc/nedrug.py``): ``"kr:…"`` from the heading's words, never its number (the
  old format numbers 투여하지 말 것 1, the new one 2, after 1. 경고): ``kr_key``. ``"kr:indications"`` and
  ``"kr:dosage"`` are the 효능효과 and 용법용량 documents; every precautions heading is watched except storage
  (``kr:storage``), and a heading not known is ``"kr:other"``, watched.

* Canada (Health Canada product monograph, ``collectors/spc/hc_dpd.py``): ``"ca:…"`` by the heading's words.
  The 2020 template numbers its headings 1–17 (1 Indications, 2 Contraindications, 3 Serious Warnings and
  Precautions Box, 4 Dosage and Administration, 5 Overdosage, 7 Warnings and Precautions, 8 Adverse Reactions,
  9 Drug Interactions …) and opens with "Recent Major Label Changes"; a heading counts only with its own number,
  in rising order. The older template's headings are unnumbered capitals (INDICATIONS AND CLINICAL USE,
  CONTRAINDICATIONS, WARNINGS AND PRECAUTIONS …), each its first whole-line appearance. The contents list (dot
  leaders), the page numbers and everything from "Patient Medication Information" / PART III on are left out.

``WATCHED`` lists the sections whose change raises a label-change issue; ``RECORD_ONLY`` (section 10
"date of revision of the text", 改訂年月) is stored and diffed but never alerts.
"""

from __future__ import annotations

import hashlib
import re

# EU SmPC sections watched for safety-relevant change.
WATCHED_EU = {"4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"}
WATCHED_US = {"us:boxed_warning", "us:recent_major_changes", "us:contraindications",
              "us:warnings_and_precautions", "us:warnings", "us:precautions", "us:adverse_reactions",
              "us:drug_interactions", "us:specific_populations", "us:overdosage"}
# "ja:precautions" is the old-format 【使用上の注意】 block, which holds 副作用 and 相互作用.
WATCHED_JA = {"ja:1", "ja:2", "ja:8", "ja:9", "ja:10", "ja:11", "ja:13", "ja:precautions"}
# Korea: the 사용상의주의사항 headings, matched on their words in this order (과량 투여 before 투여하지 말 것, an OTC
# label's "복용을 즉각 중지하고 … 상의할 것" is stop use).
KR_HEADINGS = (
    (("과량",), "kr:overdose"),
    (("투여하지 말", "복용하지 말", "사용하지 말", "투여 금기", "금기"), "kr:contraindications"),
    (("신중히",), "kr:careful_use"),
    (("중지",), "kr:stop_use"),
    (("상의할 것",), "kr:consult"),
    (("이상반응", "부작용"), "kr:adverse_reactions"),
    (("일반적 주의", "일반적주의"), "kr:general_precautions"),
    (("상호작용",), "kr:interactions"),
    (("임부", "수유부", "임신", "가임"), "kr:pregnancy"),
    (("소아", "어린이", "신생아"), "kr:paediatric"),
    (("고령자", "노인"), "kr:elderly"),
    (("운전",), "kr:driving"),
    (("임상검사",), "kr:lab_tests"),
    (("적용상",), "kr:application"),
    (("보관", "취급"), "kr:storage"),
    (("경고",), "kr:warning"),
)
WATCHED_KR = {key for _, key in KR_HEADINGS if key != "kr:storage"} | {"kr:other", "kr:indications",
                                                                       "kr:dosage"}
# Canada: the 2020 template's numbered headings (number, words it starts with, key) and the older capitals.
CA_NEW = (
    (1, "indications", "ca:indications"), (2, "contraindications", "ca:contraindications"),
    (3, "serious warnings", "ca:serious_warnings"), (4, "dosage and administration", "ca:dosage"),
    (5, "overdos", "ca:overdose"), (6, "dosage forms", "ca:forms"),
    (7, "warnings and precautions", "ca:warnings_and_precautions"), (8, "adverse reactions", "ca:adverse_reactions"),
    (9, "drug interactions", "ca:drug_interactions"), (10, "clinical pharmacology", "ca:pharmacology"),
    (11, "storage", "ca:storage"), (12, "special handling", "ca:handling"),
    (13, "pharmaceutical information", "ca:pharmaceutical"), (14, "clinical trials", "ca:clinical_trials"),
    (15, "microbiology", "ca:microbiology"), (16, "non-clinical toxicology", "ca:toxicology"),
    (17, "supporting product monographs", "ca:supporting"),
)
CA_OLD = {
    "SUMMARY PRODUCT INFORMATION": "ca:summary", "INDICATIONS AND CLINICAL USE": "ca:indications",
    "INDICATIONS": "ca:indications", "CONTRAINDICATIONS": "ca:contraindications",
    "SERIOUS WARNINGS AND PRECAUTIONS": "ca:serious_warnings",
    "WARNINGS AND PRECAUTIONS": "ca:warnings_and_precautions", "WARNINGS": "ca:warnings",
    "PRECAUTIONS": "ca:precautions", "ADVERSE REACTIONS": "ca:adverse_reactions",
    "DRUG INTERACTIONS": "ca:drug_interactions", "DOSAGE AND ADMINISTRATION": "ca:dosage",
    "OVERDOSAGE": "ca:overdose", "SYMPTOMS AND TREATMENT OF OVERDOSAGE": "ca:overdose",
    "ACTION AND CLINICAL PHARMACOLOGY": "ca:pharmacology", "ACTIONS": "ca:pharmacology",
    "STORAGE AND STABILITY": "ca:storage", "SPECIAL HANDLING INSTRUCTIONS": "ca:handling",
    "DOSAGE FORMS, COMPOSITION AND PACKAGING": "ca:forms", "PHARMACEUTICAL INFORMATION": "ca:pharmaceutical",
    "CLINICAL TRIALS": "ca:clinical_trials", "DETAILED PHARMACOLOGY": "ca:detailed_pharmacology",
    "TOXICOLOGY": "ca:toxicology", "REFERENCES": "ca:references",
}
WATCHED_CA = {"ca:recent_major_changes", "ca:indications", "ca:contraindications", "ca:serious_warnings",
              "ca:dosage", "ca:overdose", "ca:warnings_and_precautions", "ca:warnings", "ca:precautions",
              "ca:adverse_reactions", "ca:drug_interactions"}
WATCHED = WATCHED_EU | WATCHED_US | WATCHED_JA | WATCHED_KR | WATCHED_CA
RECORD_ONLY = {"10", "ja:revision"}

# Valid QRD numbers: 1–10, 2.x, 4.1–4.9, 5.1–5.3, 6.1–6.6 (and third-level 4.2.1, 4.6.1 …).
_VALID_TOP = {str(i) for i in range(1, 11)}
_VALID_SUB = ({f"4.{i}" for i in range(1, 10)} | {f"5.{i}" for i in range(1, 4)}
              | {f"6.{i}" for i in range(1, 7)} | {"2.1", "2.2"})
_HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.{0,200})$")
# Lenient splits also take a hyphen, dash or bracket after the number ("1-DENOMINAZIONE", "4.2- Posologia",
# "4.1) Indicazioni": Italian RCPs at AIFA).
_HEAD_LENIENT = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})(?:\.?\s*[)\-–]\s*|\.?\s+)(\S.{0,200})$")

US_LOINC = {
    "34066-1": "us:boxed_warning",
    "43683-2": "us:recent_major_changes",
    "42232-9": "us:precautions",
    "34070-3": "us:contraindications",
    "43685-7": "us:warnings_and_precautions",
    "34071-1": "us:warnings",
    "34084-4": "us:adverse_reactions",
    "34073-7": "us:drug_interactions",
    "43684-0": "us:specific_populations",
    "34088-5": "us:overdosage",
    "34067-9": "us:indications",
    "34068-7": "us:dosage_and_administration",
}

JA_HEADINGS = {
    "警告": "ja:1", "禁忌": "ja:2", "組成・性状": "ja:3", "組成･性状": "ja:3", "組成及び性状": "ja:3",
    "効能又は効果": "ja:4", "効能・効果": "ja:4",
    "効能又は効果に関連する注意": "ja:5", "効能・効果に関連する注意": "ja:5",
    "用法及び用量": "ja:6", "用法・用量": "ja:6",
    "用法及び用量に関連する注意": "ja:7", "用法・用量に関連する注意": "ja:7",
    "重要な基本的注意": "ja:8", "特定の背景を有する患者に関する注意": "ja:9", "相互作用": "ja:10",
    "副作用": "ja:11", "臨床検査結果に及ぼす影響": "ja:12", "過量投与": "ja:13",
    "適用上の注意": "ja:14", "その他の注意": "ja:15", "薬物動態": "ja:16", "臨床成績": "ja:17",
    "薬効薬理": "ja:18", "有効成分に関する理化学的知見": "ja:19", "取扱い上の注意": "ja:20",
    "承認条件": "ja:21", "包装": "ja:22", "主要文献": "ja:23", "文献請求先": "ja:24",
    "保険給付上の注意": "ja:25", "製造販売業者等": "ja:26",
}


def _alternation(words) -> str:
    # Longest first, so "効能又は効果に関連する注意" (5) is not read as "効能又は効果" (4).
    return "|".join(map(re.escape, sorted(words, key=len, reverse=True)))


# A heading may carry the revision marks (＊, ＊＊) of the version that changed it: "＊24. 文献請求先…".
_JA_NUM = re.compile(r"(?m)^\s*[＊*]*\s*(\d{1,2})\s*[.．]\s*(" + _alternation(JA_HEADINGS) + r")")
# Old-format 【】 headings. Only these are boundaries; a 【】 inside body text never splits a section.
JA_OLD_HEADINGS = {
    "警告": "ja:1", "禁忌": "ja:2", "原則禁忌": "ja:2", "使用上の注意": "ja:precautions",
    "組成・性状": "ja:old:composition", "組成･性状": "ja:old:composition",
    "組成": "ja:old:composition", "性状": "ja:old:composition",
    "効能・効果": "ja:old:indications", "効能又は効果": "ja:old:indications",
    "用法・用量": "ja:old:dosage", "用法及び用量": "ja:old:dosage",
    "薬物動態": "ja:old:pharmacokinetics", "臨床成績": "ja:old:clinical",
    "薬効薬理": "ja:old:pharmacology", "有効成分に関する理化学的知見": "ja:old:chemistry",
    "取扱い上の注意": "ja:old:handling", "承認条件": "ja:old:conditions", "包装": "ja:old:package",
    "主要文献": "ja:old:references", "文献請求先": "ja:old:contact",
}
_JA_OLD = re.compile(r"【\s*(" + _alternation(JA_OLD_HEADINGS) + r")[^】\n]*】")
_JA_REV = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*改訂")


def kr_key(title: str) -> str:
    """The section key of a Korean precautions heading ("3. 이상반응" → ``kr:adverse_reactions``)."""
    words = re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", title or "")
    for needles, key in KR_HEADINGS:
        if any(n in words for n in needles):
            return key
    return "kr:other"


_CA_TOC = re.compile(r"\.{5,}|…{3,}")
_CA_PAGE = re.compile(r"\bPage\s+\d+\s+of\s+\d+\b", re.I)
_CA_END = re.compile(r"^\s*(?:PART\s+III\b|PATIENT MEDICATION INFORMATION\s*$|CONSUMER INFORMATION\s*$)", re.I)
_CA_NUM = re.compile(r"^\s*(\d{1,2})\.?\s+(\S.*?)\s*$")


def _ca_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        # a contents line first: "PART III: PATIENT MEDICATION INFORMATION ......33" in the table of contents is not
        # the end of Part I (JAMP-Carvedilol, 13 Nov 2026: the split stopped at line 39 and found no section)
        if _CA_TOC.search(line):
            continue
        if _CA_END.match(line):
            break
        out.append(_CA_PAGE.sub("", line))
    return out


def _ca_new_head(line: str, last: int) -> tuple[int, str] | None:
    m = _CA_NUM.match(line)
    if not m:
        return None
    num, words = int(m.group(1)), m.group(2).casefold()
    for n, start, key in CA_NEW:
        if (n == num and n > last and words.startswith(start) and len(words) <= len(start) + 60
                and not words.endswith((")", ").", ","))):
            return n, key
    return None


# Headings of the older "prescribing information" leaflets, read only by the lenient split (Minims Phenylephrine,
# 2020: "USES", "CONTRANDICATIONS" as printed, "OTHER UNDESIRABLE EFFECTS"); the ones not watched end the section
# before them, so a watched section never runs on into storage or packaging.
CA_LEAFLET = {
    "USES": "ca:indications", "CONTRANDICATIONS": "ca:contraindications", "INTERACTIONS": "ca:drug_interactions",
    "UNDESIRABLE EFFECTS": "ca:adverse_reactions", "OTHER UNDESIRABLE EFFECTS": "ca:adverse_reactions",
    "OTHER SPECIAL WARNINGS AND PRECAUTIONS": "ca:warnings_and_precautions", "OVERDOSE": "ca:overdose",
    "PRESENTATION": "ca:presentation", "USE IN PREGNANCY AND LACTATION": "ca:pregnancy",
    "EFFECTS ON THE ABILITY TO DRIVE AND USE": "ca:driving",
    "EFFECTS ON THE ABILITY TO DRIVE AND USE MACHINES": "ca:driving", "INCOMPATIBILITIES": "ca:incompatibilities",
    "PHARMACEUTICAL PRECAUTIONS": "ca:storage", "PACKAGE QUANTITIES": "ca:package", "PHARMACOLOGY": "ca:pharmacology",
    "SUPPLIED": "ca:supplied", "STORAGE RECOMMENDATIONS": "ca:storage",
}
_CA_BILINGUAL = re.compile(r"^\s*English\s{5,}French\s*$")


def _english_column(text: str) -> str:
    """The English column of a two-column English/French leaflet (a page head "English … French", the French text
    beside the English on each line): each line up to its first run of three spaces; a line indented past the middle
    holds French only. Any other text is returned as it is."""
    lines = text.splitlines()
    if not any(_CA_BILINGUAL.match(line) for line in lines):
        return text
    out = []
    for line in lines:
        if _CA_BILINGUAL.match(line):
            continue
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        out.append("" if indent >= 40 else " " * indent + re.split(r"\s{3,}", body, maxsplit=1)[0])
    return "\n".join(out)


def split_ca_monograph(text: str) -> dict[str, str]:
    """A Health Canada product monograph's text as ``{"ca:contraindications": text, …}`` (see the module notes).

    When it finds no watched section, a lenient split is tried (17 Nov 2026, three DPD products never read): old
    headings in any case when they stand alone at the line's start ("Contraindications", "Adverse Reactions":
    Soframycin, 2023), the leaflet headings above, and only the English column of a bilingual leaflet (Minims
    Phenylephrine). A monograph that splits today splits exactly as before."""
    strict = _split_ca(_ca_lines(text), lenient=False)
    if any(k in WATCHED_CA for k in strict):
        return strict
    lenient = _split_ca(_ca_lines(_english_column(text)), lenient=True)
    return lenient if any(k in WATCHED_CA for k in lenient) else strict


def _split_ca(lines: list[str], *, lenient: bool) -> dict[str, str]:
    new = any(_ca_new_head(line, 0) for line in lines)
    out: dict[str, list[str]] = {}
    key, last = None, 0
    for line in lines:
        bare = line.strip()
        head = None
        if new:
            hit = _ca_new_head(line, last)
            if hit:
                last, head = hit
            elif (bare.casefold() == "recent major label changes" and last == 0
                  and "ca:recent_major_changes" not in out):
                head = "ca:recent_major_changes"
            elif key == "ca:recent_major_changes" and bare.casefold() == "table of contents":
                key = None
                continue
        else:
            up = re.sub(r"\s+", " ", bare).rstrip(":")
            if up in CA_OLD and up == up.upper() and CA_OLD[up] not in out:
                head = CA_OLD[up]
            elif lenient:
                big = up.upper()
                found = CA_OLD.get(big) or CA_LEAFLET.get(big)
                if found and found not in out and (up == big or not line.lstrip("\f")[:1].isspace()):
                    head = found
        if head:
            key = head
            out.setdefault(key, [])
            continue
        if key:
            out[key].append(line)
    texts = {k: "\n".join(v).strip() for k, v in out.items()}
    return {k: v for k, v in texts.items() if v}


def normalize(text: str) -> str:
    """Whitespace-insensitive form used for hashing (layout changes are not label changes)."""
    t = (text or "").replace(" ", " ").replace("　", " ")
    t = re.sub(r"-\s*\n\s*", "", t)          # hyphenation at line ends from PDF extraction
    return re.sub(r"\s+", " ", t).strip()


def section_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def hashes(sections: dict[str, str]) -> dict[str, str]:
    return {k: section_hash(v) for k, v in sections.items()}


def _num_key(num: str) -> tuple[int, ...]:
    return tuple(int(x) for x in num.split("."))


def _mostly_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.6


_DOSE = re.compile(r"^[\d.,]*\s*(mg|ml|g|%|µg|mcg|iu|ie|ui)\b", re.I)


def split_numbered(text: str) -> dict[str, str]:
    """Split an SmPC text into ``{"4.4": text, …}`` by QRD section numbers at line starts.

    Rules that keep body text from starting a section: numbers must rise (4.3 after 4.2 …); a
    top-level heading ("5. PHARMACOLOGICAL PROPERTIES") must be mostly upper-case, as the QRD
    template writes it in every language; a sub-heading must belong to the current top-level
    section; a dose ("4.5 mg") is never a heading; a sub-heading starts with a capital, as the template
    writes it in every language, so a sentence that begins with a cross-reference ("5.1 en 5.2, maar er kan
    …", a Dutch SmPC of 2024) is body text. Text before the first heading is dropped, a
    section's text excludes its heading line, and third-level headings (4.2.1) stay inside their
    parent. Upper-case-free scripts (none in the EU template) fall back to the numbering alone.
    """
    lines = (text or "").splitlines()
    strict, lenient_may_help = _split_numbered(lines, lenient=False)
    if not missing_core(strict):
        return strict
    rejoined = _rejoin_core_headings(lines)        # a core number printed apart from its title (poppler)
    if not lenient_may_help and rejoined == lines:  # no line a lenient-only rule reads differently
        return _unnumbered_48(strict)
    # A split without contraindications, warnings or undesirable effects went wrong. Two layouts did that to 55
    # Dutch SmPCs (CBG, mostly paracetamol suppositories) until 17 Nov 2026: top-level headings in sentence case
    # ("4 Klinische gegevens", never upper-case, so section 4 never began), and a dosing-table row with no word
    # in it ("6 – 9    22 - 30    500    2 – 3") taken for heading 6, so 4.3–4.9 came "after" it and were
    # dropped. Italian RCPs (AIFA) added two more on 17 Nov 2026: headings written "1-DENOMINAZIONE", "4.2- Posologia"
    # or "4.1) Indicazioni", never read as headings, and a cross-reference "4.9 “Sovradosaggio”)." in 4.2 taken for
    # heading 4.9. The lenient rules are tried only then, and only when some line reads differently under them.
    # Since 17 Nov 2026 a top-level "heading" with no letter in it is refused by the strict rules too.
    lenient, _ = _split_numbered(rejoined, lenient=True)
    return _unnumbered_48(lenient if len(missing_core(lenient)) < len(missing_core(strict)) else strict)


# QRD template's title of section 4.8, per language (a line holding exactly this, and nothing else)
_TITLE_48 = {"undesirable effects", "efeitos indesejáveis", "effets indésirables", "nebenwirkungen",
             "effetti indesiderati", "reacciones adversas", "bijwerkingen", "biverkningar", "bivirkninger",
             "haittavaikutukset", "aukaverkanir"}
# How the template's titles of the core sections begin, per language (a line starting with one of these)
_CORE_TITLE_START = {
    "4.3": ("contraindications", "controindicazioni", "contre-indications", "gegenanzeigen", "contraindicaciones",
            "contraindicações", "contra-indicações", "contra-indicaties", "kontraindikationer", "kontraindikasjoner",
            "vasta-aiheet", "frábendingar"),
    "4.4": ("special warnings and precautions", "avvertenze speciali", "mises en garde spéciales",
            "besondere warnhinweise", "advertencias y precauciones especiales", "advertências e precauções especiais",
            "bijzondere waarschuwingen", "varningar och försiktighet", "særlige advarsler", "advarsler og forsiktighet",
            "varoitukset ja käyttöön liittyvät varotoimet", "sérstök varnaðarorð"),
    "4.8": tuple(_TITLE_48),
}
_BARE_CORE = re.compile(r"^\s*(4\.[348])\.?\s*$")
_NEAR = 8                   # lines either side of a bare number searched for its title


def _rejoin_core_headings(lines: list[str]) -> list[str]:
    """A core heading whose number and title the PDF's text came out apart: poppler's pdftotext (the label watch on
    GitHub) prints Epifloxin's, Paracetamolo Mylan Italia's and Distem's "4.4" alone on a line, and "Avvertenze
    speciali e precauzioni d'impiego" two to five lines above or below it (17 Nov 2026; xpdf keeps them together).
    A line holding only 4.3, 4.4 or 4.8, with that section's template title starting a line within ``_NEAR`` lines:
    the title's line becomes "4.4 <title>" and the bare number's line is emptied. Only the lenient split reads it."""
    lines = list(lines)
    for i, line in enumerate(lines):
        m = _BARE_CORE.match(line)
        if not m:
            continue
        starts = _CORE_TITLE_START[m.group(1)]
        near = sorted(range(max(0, i - _NEAR), min(len(lines), i + _NEAR + 1)), key=lambda j: abs(j - i))
        for j in near:
            words = " ".join(lines[j].split())
            if j != i and words.casefold().startswith(starts) and len(words) <= 120:
                # the heading goes where the title is: Paracetamolo Mylan's last contraindications print between
                # the bare "4.4" and its title, and stay in 4.3
                lines[i], lines[j] = "", f"{m.group(1)} {words}"
                break
    return lines


def _unnumbered_48(sections: dict[str, str]) -> dict[str, str]:
    """Section 4.8 whose heading lost its number in the PDF's text layer: Ivabradina Teva 5 and 7.5 mg (Infomed,
    17 Nov 2026) print "4.8" as a list number that never reached the text, so "Efeitos indesejáveis" stands alone
    and the whole section ran on inside 4.7. Only when 4.7 and 4.9 were both found and 4.8 was not, the last line
    of 4.7 that is exactly the template's 4.8 title (in any EU language above) starts 4.8."""
    if "4.8" in sections or "4.7" not in sections or "4.9" not in sections:
        return sections
    lines = sections["4.7"].splitlines()
    at = next((i for i in range(len(lines) - 1, -1, -1)
               if " ".join(lines[i].split()).rstrip(".").casefold() in _TITLE_48), None)
    if at is None:
        return sections
    out = dict(sections)
    out["4.7"], out["4.8"] = "\n".join(lines[:at]).strip(), "\n".join(lines[at + 1:]).strip()
    return dict(sorted(out.items(), key=lambda kv: _num_key(kv[0])))


_SENTENCE_END = re.compile(r"[.;:,]\s*$")


def _sentence_case_heading(heading: str) -> bool:
    """A top-level heading in sentence case ("Klinische gegevens"): a capital first, a short line, and not the end
    of a sentence ("5 zetpillen in een PVC/PE zetpilstrip.")."""
    return not _starts_lower(heading) and len(heading.split()) <= 15 and not _SENTENCE_END.search(heading)


def _sentence_top(num: str, heading: str, last_top: int) -> bool:
    """A sentence-case top-level heading where one is due: the next number, or the one after it when a heading
    was lost (cover page, line wrap), so a file can also begin at 2. Shared by ``split_smpcs`` and the split."""
    gap = int(num) - last_top
    return (num in _VALID_TOP and 0 < gap <= 2 and any(c.isalpha() for c in heading)
            and _sentence_case_heading(heading) and not _DOSE.match(heading))


def _superseded_tops(lines: list[str]) -> set[int]:
    """Lines that look like a sentence-case top-level heading but give way to a later line with the same number
    before that section shows any sign of starting (an "N.x" sub-heading): "5 Patiënten met leverziekte" in 4.9,
    or a dosing row "5 Jaar en ouder" in 4.2, gives way to "5 Farmacologische eigenschappen"."""
    dropped: set[int] = set()
    open_at: dict[int, int] = {}
    for i, line in enumerate(lines):
        m = _HEAD_LENIENT.match(line)
        if not m:
            continue
        num, heading = m.group(1), m.group(2).strip()
        key = _num_key(num)
        if len(key) == 1 and num in _VALID_TOP and any(c.isalpha() for c in heading) and _sentence_case_heading(
                heading):
            if key[0] in open_at:
                dropped.add(open_at[key[0]])
            open_at[key[0]] = i
        elif len(key) == 2 and num in _VALID_SUB and not _starts_lower(heading):
            open_at.pop(key[0], None)
    return dropped


def _upper_case_file(lines: list[str]) -> bool:
    """At least two top-level QRD headings written in upper case ("1. NAAM …", "4. KLINISCHE GEGEVENS")."""
    nums = set()
    for line in lines:
        m = _HEAD_LENIENT.match(line)
        if m and m.group(1) in _VALID_TOP and _mostly_upper(m.group(2)):
            nums.add(m.group(1))
    return len(nums) >= 2


def _split_numbered(lines: list[str], *, lenient: bool) -> tuple[dict[str, str], bool]:
    """``split_numbered``'s rules, and whether any line would read differently under the lenient ones. ``lenient``
    adds three (see its comment): in a sentence-case file (fewer than two upper-case top-level headings), a
    sentence-case top-level heading is accepted where one is due (``_sentence_top``) unless a later line with the
    same number replaces it (``_superseded_tops``); a hyphen, dash or bracket may follow the number ("4.1-",
    "4.1)"); and a sub-heading never closes a bracket it did not open ("4.9 “Sovradosaggio”)."). A file whose
    headings are upper-case keeps "5 Patiënten met …" inside 4.9."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    last: tuple[int, ...] = ()
    may_help = False
    # decided by the whole file, never by its first numbered line: cover text above heading 1 ("1 Zetpil bevat …")
    # must not turn an upper-case file into a sentence-case one
    sentence_case_file = lenient and not _upper_case_file(lines)
    dropped = _superseded_tops(lines) if sentence_case_file else set()
    for i, line in enumerate(lines):
        m = (_HEAD_LENIENT if lenient else _HEAD).match(line)
        if not m and not lenient and not may_help and _HEAD_LENIENT.match(line):
            may_help = True             # "4.2- Posologia": only the lenient pattern reads it
        if m:
            num, heading = m.group(1), m.group(2).strip()
            key = _num_key(num)
            caseless = not any(c.isalpha() and c.isupper() != c.islower() for c in heading)
            # one top-level rule for both splits; a "heading" with no letter in it ("5    10    20", a table row)
            # is never one
            top_ok = len(key) == 1 and num in _VALID_TOP and any(c.isalpha() for c in heading) and (
                _mostly_upper(heading) or caseless
                or (sentence_case_file and i not in dropped and _sentence_top(num, heading, last[0] if last else 0)))
            sub_ok = (len(key) == 2 and num in _VALID_SUB and bool(last)
                      and key[0] in (last[0], last[0] + 1) and not _starts_lower(heading))
            # never the end of a cross-reference: "4.9 “Sovradosaggio”)." in 4.2's text (AIFA, Paracetamolo
            # Coop) closes a bracket it never opened, and "4.4)." or "4.4), rottura …" holds no heading
            sub_lenient = sub_ok and (any(c.isalpha() for c in heading) and heading[0] not in ",.;:)"
                                      and heading.count(")") <= heading.count("("))
            if not lenient and not may_help and (sub_ok != sub_lenient or (
                    len(key) == 1 and not top_ok and num in _VALID_TOP and any(c.isalpha() for c in heading)
                    and _sentence_case_heading(heading))):
                may_help = True
            if lenient:
                sub_ok = sub_lenient
            if (top_ok or sub_ok) and key > last and not _DOSE.match(heading) and (
                    current is not None or key[0] <= 2):
                current, last = num, key
                out.setdefault(current, [])
                continue
        if current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}, may_help


def _starts_lower(heading: str) -> bool:
    first = next((c for c in heading if c.isalpha()), "")
    return first.islower()


CORE_EU = ("4.3", "4.4", "4.8")


def missing_core(sections: dict[str, str], prefix: str = "") -> list[str]:
    """The core SmPC sections (contraindications, warnings, undesirable effects) a split did not find. Every
    SmPC has all three headings; a split without one went wrong, and is never stored as a label without it."""
    return [k for k in CORE_EU if prefix + k not in sections]


def split_japanese(text: str) -> dict[str, str]:
    """Split a 添付文書 text into ``{"ja:11": text, …}`` (new numbered format, else old 【】 format)."""
    text = (text or "").replace("\f", "\n")     # a page break starts a line too
    marks: list[tuple[int, int, str]] = []
    last = 0
    for m in _JA_NUM.finditer(text):
        num = int(m.group(1))
        key = JA_HEADINGS[m.group(2)]
        if key != f"ja:{num}" or num <= last:
            continue
        last = num
        marks.append((m.start(), m.end(), key))
    if not marks:
        for m in _JA_OLD.finditer(text):
            marks.append((m.start(), m.end(), JA_OLD_HEADINGS[m.group(1)]))
    out: dict[str, str] = {}
    for i, (_s, e, key) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[e:end].strip()
        if key in out:
            out[key] += "\n" + body
        else:
            out[key] = body
    rev = _JA_REV.search(text)
    if rev:
        out["ja:revision"] = rev.group(0)
    return out


_SMPC_PREFIX = re.compile(r"^smpc\d+:")


def split_smpcs(text: str) -> list[str]:
    """The SmPCs of one product-information text, in order: a new one starts at each "1. NAME OF THE MEDICINAL
    PRODUCT" heading (number 1, mostly upper-case, in any language) once the SmPC before it reached section 6.
    Before 7 Nov 2026 every SmPC after the first ran on inside the first one's section 10. A file in sentence case
    (fewer than two upper-case top-level headings, CBG's "1 Naam van het geneesmiddel") moves on by the shared
    ``_sentence_top`` rule, and a new SmPC starts only at a line repeating the first one's heading 1."""
    lines = (text or "").splitlines()
    upper = _upper_case_file(lines)
    blocks: list[list[str]] = [[]]
    top = 0
    first: str | None = None        # a sentence-case file's heading 1, as the first SmPC writes it
    for line in lines:
        m = _HEAD.match(line)
        if m and "." not in m.group(1):
            num, heading = int(m.group(1)), m.group(2).strip()
            if upper:
                if num == 1 and top >= 6 and _mostly_upper(heading):
                    blocks.append([])
                    top = 0
                elif _mostly_upper(heading) and num > top:
                    top = num
            elif num == 1 and top >= 6 and first is not None and " ".join(heading.split()).casefold() == first:
                blocks.append([])
                top = 1
            elif _sentence_top(m.group(1), heading, top):
                if num == 1 and first is None:
                    first = " ".join(heading.split()).casefold()
                top = num
        blocks[-1].append(line)
    return ["\n".join(b) for b in blocks if any(x.strip() for x in b)]


def split_smpc_sections(text: str) -> dict[str, str]:
    """``split_numbered`` of each SmPC in ``text``: the first one's keys as they are, the next ``"smpc2:4.4"`` …"""
    out: dict[str, str] = {}
    for n, block in enumerate(split_smpcs(text), start=1):
        for key, body in split_numbered(block).items():
            out[key if n == 1 else f"smpc{n}:{key}"] = body
    return out


def eu_wanted(key: str) -> bool:
    """An EU-numbered section the label watch keeps: a watched one (4.1–4.9, sub-sections by their parent) or 10,
    the revision date (recorded only), of any SmPC in the file (``smpc2:4.4``)."""
    bare = _SMPC_PREFIX.sub("", key)
    return bare == "10" or bare in WATCHED_EU or ".".join(bare.split(".")[:2]) in WATCHED_EU


EDGE_LINES = 6            # lines at the top and at the bottom of a page where a running header or footer sits
_DIGITS = re.compile(r"\d+")


def _line_key(line: str) -> str:
    return _DIGITS.sub("#", " ".join(line.split())).lower()


def strip_running_lines(text: str) -> str:
    """``text`` (pages joined with form feeds) without its running headers and footers: a line printed once on a
    page, at its top or bottom, on at least half the pages, digits aside ("Sandoz B.V.   Page 5/22", "1311-V14b",
    "Oktober 2025"), and a short line printed once on most pages wherever it falls (the CBG's "Oude versie" stamp).
    They change with every new version of the file, and left in they would make every section of it look revised
    (CBG Carvedilol Sandoz, December 2025 against July 2026: all of 4.2–4.9). A line printed more than once on a
    page is the text's own (a table's "Vaak"). A file of fewer than four pages is left as it is."""
    pages = text.split("\f")
    if len(pages) < 4:
        return text
    lines = [p.splitlines() for p in pages]
    edge: dict[str, int] = {}
    anywhere: dict[str, int] = {}
    seen: list[tuple[set[int], dict[str, int]]] = []
    for page in lines:
        filled = [i for i, ln in enumerate(page) if ln.strip()]
        ends = set(filled[:EDGE_LINES] + filled[-EDGE_LINES:])
        counts: dict[str, int] = {}
        for i in filled:
            k = _line_key(page[i])
            counts[k] = counts.get(k, 0) + 1
        seen.append((ends, counts))
        for k in {_line_key(page[i]) for i in ends if len(page[i].strip()) <= 120}:
            if counts[k] == 1:
                edge[k] = edge.get(k, 0) + 1
        for k, n in counts.items():
            if n == 1 and len(k) <= 40:
                anywhere[k] = anywhere.get(k, 0) + 1
    many = len(pages)
    at_edge = {k for k, n in edge.items() if n * 2 >= many}
    stamps = {k for k, n in anywhere.items() if n * 5 >= many * 3}
    if not at_edge and not stamps:
        return text
    out = []
    for page, (ends, counts) in zip(lines, seen, strict=True):
        kept = []
        for i, ln in enumerate(page):
            k = _line_key(ln)
            if counts.get(k) == 1 and ((i in ends and k in at_edge) or k in stamps):
                continue
            kept.append(ln)
        out.append("\n".join(kept))
    return "\f".join(out)


def eu_label_sections(text: str) -> dict[str, str]:
    """The kept sections of a national SmPC file, each SmPC on its own: one file can hold two (Infomed's
    Ivabradina Aurovitas: one per strength), and the second must not run on inside the first one's section 10.
    The file's running headers and footers are taken out first (``strip_running_lines``)."""
    return {k: v for k, v in split_smpc_sections(strip_running_lines(text)).items() if eu_wanted(k)}


def cut_annex_i(text: str) -> str:
    """The SmPC part of an EPAR product-information PDF: Annex I up to Annex II."""
    m_start = re.search(r"(?im)^\s*(ANNEX I|ANHANG I|ANNEXE I|ALLEGATO I|ANEXO I|BIJLAGE I)\s*$",
                        text)
    m_end = re.search(r"(?im)^\s*(ANNEX II|ANHANG II|ANNEXE II|ALLEGATO II|ANEXO II|BIJLAGE II)\s*$",
                      text[m_start.end():] if m_start else text)
    start = m_start.end() if m_start else 0
    end = start + m_end.start() if m_end else len(text)
    return text[start:end]


def watched_changes(changed: list[str]) -> list[str]:
    """Sections among ``changed`` that may raise an issue (QRD sub-sections count via parent)."""
    out = []
    for key in changed:
        bare = _SMPC_PREFIX.sub("", key)
        if bare in RECORD_ONLY:
            continue
        parent = ".".join(bare.split(".")[:2])
        if bare in WATCHED or parent in WATCHED:
            out.append(key)
    return out
