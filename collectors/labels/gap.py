"""Our label against an originator's label change: which of the sentences the originator added does our label
already say? Plain word overlap, in one language, explained on screen; never a translation.

The same check ran in the browser until November 2026 (``web/src/lib/labelGap.ts``); it moved here so the gap is
computed once, stored (``label_gap``, migration 0043) and read by the screen and the weekly report alike. Pure
functions, no I/O.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Valid QRD numbers, as collectors/spc/sections.py: 1–10, 2.1–2.2, 4.1–4.9, 5.1–5.3, 6.1–6.6.
VALID = ({str(i) for i in range(1, 11)} | {"2.1", "2.2"} | {f"4.{i}" for i in range(1, 10)}
         | {f"5.{i}" for i in range(1, 4)} | {f"6.{i}" for i in range(1, 7)})
HEAD = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.{0,200})$")

# The EU SmPC section an originator's section corresponds to (US PI and Japanese headings mapped).
EU_SECTION = {
    "us:boxed_warning": "4.4",
    "us:contraindications": "4.3",
    "us:warnings_and_precautions": "4.4",
    "us:warnings": "4.4",
    "us:adverse_reactions": "4.8",
    "us:drug_interactions": "4.5",
    "us:specific_populations": "4.6",
    "us:overdosage": "4.9",
    "us:indications": "4.1",
    "us:dosage_and_administration": "4.2",
    "ja:1": "4.4",
    "ja:2": "4.3",
    "ja:8": "4.4",
    "ja:9": "4.4",
    "ja:10": "4.5",
    "ja:11": "4.8",
    "ja:13": "4.9",
    "ja:precautions": "4.4",
}

STOP = frozenset((
    "the and for with that this from have been were which when what will shall should would could may might must "
    "also into than then there their these those such other some more most very only each both after before "
    "during while about above below between under over again further once here where your patients patient "
    "treatment taking take taken used using dose doses product medicine medicinal"
).split())

COVERED_AT = 0.75       # share of the added sentence's content words found in one sentence of ours
PARTLY_AT = 0.4
MIN_LETTERS = 12        # shorter fragments are headings and bullets, not sentences

_LETTERS = re.compile(r"[^\W\d_]+", re.UNICODE)
_NOT_LETTER = re.compile(r"[\W\d_]", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|(?<=。)\s*|\s+[•▪·]\s+")


def _num_key(n: str) -> list[int]:
    return [int(x) for x in n.split(".")]


def _after(a: list[int], b: list[int] | None) -> bool:
    if b is None:
        return True
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else -1
        y = b[i] if i < len(b) else -1
        if x != y:
            return x > y
    return False


def normalize(t: str) -> str:
    """Whitespace-insensitive text, with line-end hyphenation from PDF extraction joined."""
    t = re.sub(r"[ 　]", " ", t or "")
    t = re.sub(r"-\s*\n\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def split_sections(text: str) -> dict[str, str]:
    """An SmPC / leaflet text split into its numbered sections ("4.4" → text). A heading is a valid QRD number at
    the start of a line, later in order than the one before it, so a numbered list inside a section ("1. Take
    with food") never starts a new section. Third-level headings (4.2.1) stay inside their section."""
    out: dict[str, str] = {}
    current: str | None = None
    last: list[int] | None = None
    for line in re.sub(r"\r\n?", "\n", text or "").split("\n"):
        m = HEAD.match(line)
        if m:
            parts = m.group(1).split(".")
            key = ".".join(parts[:2])
            k = _num_key(m.group(1))
            if key in VALID and _after(k, last):
                last = k
                if len(parts) <= 2:
                    current = key
                    out[current] = f"{out[current]}\n" if out.get(current) else ""
                    continue
        if current is not None:
            out[current] = f"{out[current]}\n{line}" if out.get(current) else line
    for k in list(out):
        out[k] = normalize(out[k])
        if not out[k]:
            del out[k]
    return out


def eu_section(key: str) -> str | None:
    """The EU SmPC section an originator's section corresponds to; None for one with no counterpart."""
    key = key or ""
    if key[:1].isdigit():
        return ".".join(key.split(".")[:2])
    return EU_SECTION.get(key)


def sentences(text: str) -> list[str]:
    """Sentences, split after . ; ! ? or 。; short fragments (headings, bullets) are dropped."""
    out = []
    for raw in _SENTENCE_END.split(normalize(text)):
        s = raw.strip().lstrip("•▪· ").strip()
        if len(_NOT_LETTER.sub("", s)) >= MIN_LETTERS:
            out.append(s)
    return out


def added_sentences(before: str, after: str) -> list[str]:
    """The sentences of ``after`` that are not in ``before`` (compared whitespace- and case-insensitively)."""
    had = {s.lower() for s in sentences(before or "")}
    return [s for s in sentences(after or "") if s.lower() not in had]


def content_words(s: str) -> set[str]:
    """Content words: letters only, four or more, a plural -s dropped, common words left out."""
    out: set[str] = set()
    for raw in _LETTERS.findall((s or "").lower()):
        if len(raw) < 4 or raw in STOP:
            continue
        out.add(raw[:-1] if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss") else raw)
    return out


def compare_with_ours(added: list[str], ours: str) -> list[dict[str, Any]]:
    """For each sentence the originator added, how much of it our section already says:
    ``{sentence, status: covered|partly|missing, score 0–1, closest: our closest sentence or None}``."""
    our = [(s, content_words(s)) for s in sentences(ours or "")]
    results = []
    for sentence in added:
        w = content_words(sentence)
        best, closest = 0.0, None
        if w:
            for s, ow in our:
                score = len(w & ow) / len(w)
                if score > best:
                    best, closest = score, s
        status = "covered" if best >= COVERED_AT else "partly" if best >= PARTLY_AT else "missing"
        results.append({"sentence": sentence, "status": status, "score": round(best * 100) / 100,
                        "closest": closest if best > 0 else None})
    return results


def same_language(a: str | None, b: str | None) -> bool:
    """Whether two BCP-47 codes are the same language ("en" and "en-GB" are)."""
    if not a or not b:
        return False
    return a.lower().split("-")[0] == b.lower().split("-")[0]


def _loaded(value: Any) -> Any:
    inner = getattr(value, "obj", value)
    if isinstance(inner, (str, bytes)):
        try:
            return json.loads(inner)
        except ValueError:
            return None
    return inner


def label_gap(diff: Any, our_sections: Any, our_lang: str | None, their_lang: str | None) -> dict[str, Any]:
    """What ``label_gap.gap`` holds for one label change against one version of our label: per watched safety
    section the originator changed (4.1–4.9, US and Japanese headings mapped), each sentence it added with its
    status against the same section of ours, and the counts. Across languages nothing is compared."""
    base = {"lang_match": same_language(our_lang, their_lang), "our_lang": our_lang, "their_lang": their_lang,
            "covered": 0, "partly": 0, "missing": 0, "sections": []}
    if not base["lang_match"]:
        return base
    changes = _loaded(diff) or []
    ours = _loaded(our_sections) or {}
    if not isinstance(changes, list) or not isinstance(ours, dict):
        return base
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        section = str(ch.get("section") or "")
        target = eu_section(section)
        if not target or not target.startswith("4."):
            continue        # section 10 (date of revision) and the like: nothing of ours to compare with
        added = added_sentences(str(ch.get("before") or ""), str(ch.get("after") or ""))
        our_text = ours.get(target)
        our_text = our_text if isinstance(our_text, str) and our_text.strip() else ""
        if our_text:
            results = compare_with_ours(added, our_text)
        else:
            results = [{"sentence": s, "status": "missing", "score": 0, "closest": None} for s in added]
        counts = {k: sum(1 for r in results if r["status"] == k) for k in ("covered", "partly", "missing")}
        base["sections"].append({"section": section, "our_section": target, "our_text": bool(our_text),
                                 **counts, "added": results})
        for k, n in counts.items():
            base[k] += n
    return base
