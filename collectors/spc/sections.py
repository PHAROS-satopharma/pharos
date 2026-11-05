"""PHAROS — split a product label (SmPC / US PI / Japanese 添付文書) into numbered sections.

Section keys are language-neutral where the label format is:

* EU/UK/CH SmPC (QRD template, every EU language): ``"4.3"``, ``"4.4"``, ``"4.8"``, ``"10"`` …
  Headings are recognised by their number at the start of a line ("4.4 Advertencias y
  precauciones especiales de empleo", "4.4. Mises en garde…", "4.8 Undesirable effects"); the
  heading words are never translated or compared, so every language splits the same way.
* US PI (DailyMed SPL, by LOINC section code): ``"us:boxed_warning"``, ``"us:contraindications"``,
  ``"us:warnings_and_precautions"``, ``"us:warnings"``, ``"us:adverse_reactions"``,
  ``"us:drug_interactions"``, ``"us:specific_populations"``, ``"us:overdosage"``.
* Japan (new-format 添付文書, 2019+): every numbered heading 1–26 is a boundary (``"ja:3"`` 組成・性状,
  ``"ja:5"`` 効能又は効果に関連する注意 … so their text never runs on inside the section before);
  watched are ``"ja:1"`` 警告, ``"ja:2"`` 禁忌, ``"ja:8"`` 重要な基本的注意,
  ``"ja:9"`` 特定の背景を有する患者に関する注意, ``"ja:10"`` 相互作用, ``"ja:11"`` 副作用,
  ``"ja:13"`` 過量投与. Old format (before 2019): 【警告】→ ja:1, 【禁忌】【原則禁忌】→ ja:2 and the
  whole 【使用上の注意】 block (慎重投与, 重要な基本的注意, 相互作用, 副作用 … numbered inside it) →
  ``"ja:precautions"``, which is watched; the other 【】 headings (【組成・性状】【効能・効果】
  【用法・用量】【薬物動態】 …) end the section before them and are not watched.

``WATCHED`` lists the sections whose change raises a label-change issue; ``RECORD_ONLY`` (section 10
"date of revision of the text", 改訂年月) is stored and diffed but never alerts.
"""

from __future__ import annotations

import hashlib
import re

# EU SmPC sections watched for safety-relevant change.
WATCHED_EU = {"4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "4.9"}
WATCHED_US = {"us:boxed_warning", "us:contraindications", "us:warnings_and_precautions",
              "us:warnings", "us:adverse_reactions", "us:drug_interactions",
              "us:specific_populations", "us:overdosage"}
# "ja:precautions" is the old-format 【使用上の注意】 block, which holds 副作用 and 相互作用.
WATCHED_JA = {"ja:1", "ja:2", "ja:8", "ja:9", "ja:10", "ja:11", "ja:13", "ja:precautions"}
WATCHED = WATCHED_EU | WATCHED_US | WATCHED_JA
RECORD_ONLY = {"10", "ja:revision"}

# Valid QRD numbers: 1–10, 2.x, 4.1–4.9, 5.1–5.3, 6.1–6.6 (and third-level 4.2.1, 4.6.1 …).
_VALID_TOP = {str(i) for i in range(1, 11)}
_VALID_SUB = ({f"4.{i}" for i in range(1, 10)} | {f"5.{i}" for i in range(1, 4)}
              | {f"6.{i}" for i in range(1, 7)} | {"2.1", "2.2"})
_HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.{0,200})$")

US_LOINC = {
    "34066-1": "us:boxed_warning",
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


_JA_NUM = re.compile(r"(?m)^\s*(\d{1,2})\s*[.．]\s*(" + _alternation(JA_HEADINGS) + r")")
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
    section; a dose ("4.5 mg") is never a heading. Text before the first heading is dropped, a
    section's text excludes its heading line, and third-level headings (4.2.1) stay inside their
    parent. Upper-case-free scripts (none in the EU template) fall back to the numbering alone.
    """
    out: dict[str, list[str]] = {}
    current: str | None = None
    last: tuple[int, ...] = ()
    for line in (text or "").splitlines():
        m = _HEAD.match(line)
        if m:
            num, heading = m.group(1), m.group(2).strip()
            key = _num_key(num)
            top_ok = len(key) == 1 and num in _VALID_TOP and (
                _mostly_upper(heading) or not any(c.isalpha() and c.isupper() != c.islower()
                                                  for c in heading))
            sub_ok = (len(key) == 2 and num in _VALID_SUB and bool(last)
                      and key[0] in (last[0], last[0] + 1))
            if (top_ok or sub_ok) and key > last and not _DOSE.match(heading) and (
                    current is not None or key[0] <= 2):
                current, last = num, key
                out.setdefault(current, [])
                continue
        if current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def split_japanese(text: str) -> dict[str, str]:
    """Split a 添付文書 text into ``{"ja:11": text, …}`` (new numbered format, else old 【】 format)."""
    text = text or ""
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
        if key in RECORD_ONLY:
            continue
        parent = ".".join(key.split(".")[:2])
        if key in WATCHED or parent in WATCHED:
            out.append(key)
    return out
