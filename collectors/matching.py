"""Term matching in the source's own language, with offsets back to the original text.

Normalisation (applied identically to text and terms):
  NFKC (half/full-width katakana and Latin unify), casefold, accents stripped for Latin, Greek and
  Cyrillic only (Japanese dakuten are kept), soft hyphens and zero-width characters removed,
  whitespace collapsed, Arabic tashkeel/tatweel stripped and alef / ya / ta marbuta unified.
  A line-end hyphen (``Lornoxi-\\ncam``) is handled by matching two variants of the text: one with
  the hyphen and line break removed and one with the hyphen kept. Both keep an offset map, so every
  hit points at the exact characters of the original.

Modes:
  stem       word start + term + up to 6 word characters (``lornoksikaamia``, ``Lornoxicams``);
             in a multi-word term every earlier word may take up to 3 extra characters.
  exact      word-bounded (brands, short acronyms such as AINS or FANS).
  substring  anywhere (Japanese, Korean); internal spaces in the term are optional.
  Arabic terms (any mode) accept the prefixes و/ف, ب/ل/ك and ال, and up to 4 suffix letters.

Exclusions: a hit overlapping an occurrence of one of the term's exclusions is dropped.
Word boundaries only count Latin/Greek/Cyrillic/Arabic letters and digits, so an INN written inside
Japanese or Korean text still matches.

Confidence: structured fields and text hits are 'high'. On OCR text only, near-misses found by
trigram similarity (like pg_trgm) are added as 'possible' — they go to review, never to an alert.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

# ───────────────────────────── normalisation ─────────────────────────────

_DROP = {"­", "​", "‌", "‍", "⁠", "﻿", "ـ"}  # soft hyphen, ZW*, tatweel
_HYPHENS = {"-", "‐", "‑", "‒", "–", "­"}
_CLUSTER_MARKS = {"ﾞ", "ﾟ", "゙", "゚"}
_ARABIC_MAP = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
               "ى": "ي", "ی": "ي", "ة": "ه", "ؤ": "و",
               "ئ": "ي", "ک": "ك"}
_LINE_BREAK_AFTER_HYPHEN = re.compile(r"[ \t]*\r?\n[ \t]*(?=\w)")
# every dash normalise() rejoins across a line break, so the "hyphen kept" variant is built for each
_HAS_LINE_HYPHEN = re.compile("[" + re.escape("".join(sorted(_HYPHENS))) + r"][ \t]*\r?\n")


def _strippable(ch: str) -> bool:
    o = ord(ch)
    return (0x41 <= o <= 0x24F or 0x1E00 <= o <= 0x1EFF or 0x2C60 <= o <= 0x2C7F
            or 0xA720 <= o <= 0xA7FF or 0x370 <= o <= 0x3FF or 0x1F00 <= o <= 0x1FFF
            or 0x400 <= o <= 0x52F)


def _is_tashkeel(ch: str) -> bool:
    o = ord(ch)
    return 0x64B <= o <= 0x65F or o == 0x670 or 0x6D6 <= o <= 0x6ED


def _fold_char(c: str) -> str:
    """One NFKC character → its matching form (possibly empty or several characters)."""
    if c in _DROP or _is_tashkeel(c):
        return ""
    if c in _ARABIC_MAP:
        return _ARABIC_MAP[c]
    if _strippable(c):
        base = "".join(d for d in unicodedata.normalize("NFD", c) if not unicodedata.combining(d))
        return base.casefold()
    if unicodedata.combining(c) and c not in ("゙", "゚"):
        return ""  # stray combining mark on a Latin base already split off
    return c.casefold()


@dataclass
class NormText:
    """Normalised text plus, for each normalised character, the original span it came from."""
    text: str
    starts: list[int]
    ends: list[int]

    def span(self, a: int, b: int) -> tuple[int, int]:
        return self.starts[a], self.ends[b - 1]


def normalise(text: str, *, rejoin: bool = True) -> NormText:
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    n = len(text)
    i = 0

    def emit(s: str, a: int, b: int) -> None:
        for ch in s:
            if ch.isspace():
                if not out or out[-1] == " ":
                    if out:
                        ends[-1] = b
                    continue
                ch = " "
            out.append(ch)
            starts.append(a)
            ends.append(b)

    while i < n:
        c = text[i]
        if c in _HYPHENS:
            m = _LINE_BREAK_AFTER_HYPHEN.match(text, i + 1)
            if m and "\n" in m.group(0):
                if rejoin or c == "­":
                    i = m.end()  # Lornoxi-\ncam → lornoxicam
                    continue
                emit("-", i, i + 1)
                emit(" ", i + 1, m.end())
                i = m.end()
                continue
        j = i + 1
        while j < n and (unicodedata.combining(text[j]) or text[j] in _CLUSTER_MARKS
                         or "︀" <= text[j] <= "️"):
            j += 1
        cluster = text[i:j]
        if cluster in _DROP:
            i = j
            continue
        folded = "".join(_fold_char(ch) for ch in unicodedata.normalize("NFKC", cluster))
        emit(folded, i, j)
        i = j
    return NormText("".join(out), starts, ends)


def norm(s: str) -> str:
    """Normalised form of a short string (a term, an exclusion)."""
    return normalise(s).text.strip()


# ───────────────────────────── terms ─────────────────────────────

_W = r"[0-9a-zß-ɏͰ-ϿЀ-ԯḀ-ỿء-يٮ-ۓ]"
_ARABIC = re.compile(r"[؀-ۿ]")
_AR_PREFIX = "(?:و|ف)?(?:ب|ل|ك)?(?:ال|لل)?"


@dataclass(frozen=True)
class Term:
    id: str
    term: str
    lang: str
    mode: str = "stem"                  # stem | exact | substring
    exclusions: tuple[str, ...] = ()
    ingredient_id: str | None = None
    class_id: str | None = None
    kind: str = "inn"                   # inn | salt | brand | code | synonym | class

    @property
    def is_class(self) -> bool:
        return self.class_id is not None and self.ingredient_id is None


def _token_rx(token: str) -> str:
    return re.escape(token).replace(r"\-", r"[-\s]?")


def compile_term(term: Term) -> re.Pattern[str]:
    t = norm(term.term)
    if not t:
        raise ValueError(f"empty term {term.id}")
    tokens = t.split(" ")
    if _ARABIC.search(t):
        body = r"\s+".join(_token_rx(tok) for tok in tokens)
        return re.compile(rf"(?<!{_W}){_AR_PREFIX}{body}{_W}{{0,4}}(?!{_W})")
    if term.mode == "substring":
        return re.compile(r"\s*".join(_token_rx(tok) for tok in tokens))
    if term.mode == "exact":
        return re.compile(rf"(?<!{_W})" + r"\s+".join(_token_rx(tok) for tok in tokens) + rf"(?!{_W})")
    parts = [_token_rx(tok) + (f"{_W}{{0,3}}" if k < len(tokens) - 1 else f"{_W}{{0,6}}")
             for k, tok in enumerate(tokens)]
    return re.compile(rf"(?<!{_W})" + r"\s+".join(parts) + rf"(?!{_W})")


# ───────────────────────────── trigram similarity ─────────────────────────────

def trigrams(word: str) -> set[str]:
    padded = f"  {word} "
    return {padded[k:k + 3] for k in range(len(padded) - 2)}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _bigrams(s: str) -> set[str]:
    return {s[k:k + 2] for k in range(len(s) - 1)} or {s}


FUZZY_THRESHOLD = 0.55
FUZZY_CJK_THRESHOLD = 0.6


# ───────────────────────────── hits ─────────────────────────────

@dataclass
class Hit:
    term: Term
    field: str                     # structured | title | body | attachment
    start: int | None              # offsets in the ORIGINAL text of that field
    end: int | None
    matched_text: str              # the words as they appear in the original
    snippet: str
    confidence: str = "high"       # high | possible
    attachment_index: int | None = None
    path: str | None = None        # structured field path

    @property
    def ingredient_id(self) -> str | None:
        return self.term.ingredient_id

    @property
    def class_id(self) -> str | None:
        return self.term.class_id


def make_snippet(original: str, start: int, end: int, width: int = 160) -> str:
    pad = max(20, (width - (end - start)) // 2)
    a, b = max(0, start - pad), min(len(original), end + pad)
    s = re.sub(r"\s+", " ", original[a:b]).strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(original) else "")


def _primary(lang: str | None) -> str | None:
    return lang.split("-")[0].lower() if lang else None


@dataclass
class _Compiled:
    term: Term
    rx: re.Pattern[str]
    nterm: str
    exclusions: tuple[str, ...]
    latin: bool


class Matcher:
    """Compile the active watchlist once per run; match many texts."""

    def __init__(self, terms: Iterable[Term]) -> None:
        self.compiled: list[_Compiled] = []
        for t in terms:
            try:
                rx = compile_term(t)
            except ValueError:
                continue
            nterm = norm(t.term)
            self.compiled.append(_Compiled(
                term=t, rx=rx, nterm=nterm,
                exclusions=tuple(e for e in (norm(x) for x in t.exclusions) if e),
                latin=bool(re.fullmatch(rf"(?:{_W}|[\s\-])+", nterm)) and not _ARABIC.search(nterm),
            ))

    def __bool__(self) -> bool:
        return bool(self.compiled)

    def _applies(self, c: _Compiled, lang: str | None) -> bool:
        """Ingredient terms apply to every text; class terms only in their own language."""
        if not c.term.is_class or lang is None:
            return True
        return _primary(c.term.lang) == _primary(lang)

    def match_text(self, text: str | None, field: str, *, lang: str | None = None,
                   ocr: bool = False, attachment_index: int | None = None) -> list[Hit]:
        if not text or not self.compiled:
            return []
        variants = [normalise(text, rejoin=True)]
        if _HAS_LINE_HYPHEN.search(text):
            variants.append(normalise(text, rejoin=False))
        hits: dict[tuple, Hit] = {}
        for c in self.compiled:
            if not self._applies(c, lang):
                continue
            for nt in variants:
                excl_spans = [(m.start(), m.end()) for e in c.exclusions
                              for m in re.finditer(re.escape(e), nt.text)]
                for m in c.rx.finditer(nt.text):
                    a, b = m.start(), m.end()
                    while a < b and nt.text[a] == " ":
                        a += 1
                    if a >= b or any(x < b and a < y for x, y in excl_spans):
                        continue
                    s, e = nt.span(a, b)
                    key = (c.term.id, s)
                    if key not in hits:
                        hits[key] = Hit(c.term, field, s, e, text[s:e], make_snippet(text, s, e),
                                        "high", attachment_index)
            if ocr:
                for h in self._fuzzy(c, variants[0], text, field, attachment_index):
                    if not any(o.term.id == c.term.id and o.start is not None and h.start is not None
                               and o.start < h.end and h.start < o.end for o in hits.values()):
                        hits.setdefault((c.term.id, h.start), h)
        return sorted(hits.values(), key=lambda h: (h.start or 0, h.term.id))

    def _fuzzy(self, c: _Compiled, nt: NormText, text: str, field: str,
               attachment_index: int | None) -> list[Hit]:
        out: list[Hit] = []
        if c.latin and " " not in c.nterm and len(c.nterm) >= 6:
            for m in re.finditer(rf"{_W}+", nt.text):
                tok = m.group(0)
                if abs(len(tok) - len(c.nterm)) > 7 or len(tok) < len(c.nterm) - 2:
                    continue
                if c.rx.fullmatch(tok):
                    continue
                sim = max(similarity(tok, c.nterm), similarity(tok[:len(c.nterm)], c.nterm))
                if sim < FUZZY_THRESHOLD:
                    continue
                if any(max(similarity(tok, e), similarity(tok[:len(e)], e)) >= sim
                       for e in c.exclusions):
                    continue
                s, e = nt.span(m.start(), m.end())
                out.append(Hit(c.term, field, s, e, text[s:e], make_snippet(text, s, e),
                               "possible", attachment_index))
        elif c.term.mode == "substring" and len(c.nterm) >= 4:
            target = _bigrams(c.nterm.replace(" ", ""))
            L = len(c.nterm)
            k = 0
            while k + L <= len(nt.text):
                window = nt.text[k:k + L]
                wb = _bigrams(window)
                sim = len(wb & target) / len(wb | target)
                if sim >= FUZZY_CJK_THRESHOLD and not c.rx.search(window):
                    if not any(len(_bigrams(e) & wb) / len(_bigrams(e) | wb) >= sim
                               for e in c.exclusions):
                        s, e = nt.span(k, k + L)
                        out.append(Hit(c.term, field, s, e, text[s:e], make_snippet(text, s, e),
                                       "possible", attachment_index))
                        k += L
                        continue
                k += 1
        return out

    def match_structured(self, structured: dict | None, paths: Iterable[str]) -> list[Hit]:
        """Structured fields (e.g. EMA active_substances) — always confidence 'high'."""
        if not structured:
            return []
        hits: list[Hit] = []
        for path in paths:
            value = get_path(structured, path)
            if value in (None, "", [], {}):
                continue
            s = value if isinstance(value, str) else "; ".join(str(v) for v in _flatten(value))
            for h in self.match_text(s, "structured", lang="en"):
                h.path = path
                h.snippet = make_snippet(f"{path}: {s}", h.start + len(path) + 2,
                                         h.end + len(path) + 2)
                hits.append(h)
        return hits


def _flatten(value) -> list:
    if isinstance(value, dict):
        return [x for v in value.values() for x in _flatten(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _flatten(v)]
    return [value]


def get_path(data: dict, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            cur = [x.get(part) if isinstance(x, dict) else None for x in cur]
        else:
            return None
        if cur is None:
            return None
    return cur


# ───────────────────────────── document-level summary ─────────────────────────────

@dataclass
class DocumentMatch:
    hits: list[Hit] = field(default_factory=list)

    @property
    def ingredient_ids(self) -> set[str]:
        return {h.term.ingredient_id for h in self.hits if h.term.ingredient_id}

    @property
    def class_ids(self) -> set[str]:
        return {h.term.class_id for h in self.hits if h.term.class_id and not h.term.ingredient_id}

    @property
    def class_only(self) -> bool:
        return bool(self.hits) and not self.ingredient_ids

    @property
    def has_high(self) -> bool:
        """A sure hit on a watched INGREDIENT. A class term ("NSAID") never makes an uncertain
        ingredient hit (an OCR near-miss) alert-worthy: 'possible' never alerts on its own."""
        return any(h.confidence == "high" and h.term.ingredient_id for h in self.hits)

    @property
    def brands(self) -> set[str]:
        return {norm(h.term.term) for h in self.hits if h.term.kind == "brand"}

    def __bool__(self) -> bool:
        return bool(self.hits)
