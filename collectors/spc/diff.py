"""PHAROS — word-by-word diff of label sections, in the label's own language.

``diff_sections(before, after)`` compares two ``{section: text}`` maps (normalised with
``sections.normalize``) and returns one entry per section whose text changed, was added or was
removed::

    {"section": "4.4", "before": "<old text>", "after": "<new text>",
     "changes": [{"op": "replace", "before": "renal", "after": "renal or hepatic"}, …]}

That list is stored as ``spc_change.diff`` (jsonb) and shown to reviewers as is — never translated.

Tokens are words for alphabetic scripts and single characters for CJK (Japanese, Korean,
Chinese), where words are not separated by spaces.
"""

from __future__ import annotations

import difflib
import re

from collectors.spc.sections import normalize

_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯＀-￯]")
_TOKEN = re.compile(r"[぀-ヿ㐀-鿿가-힯＀-￯]|[^\s぀-ヿ"
                    r"㐀-鿿가-힯＀-￯]+")
MAX_TEXT = 20000       # a section longer than this is stored truncated in the diff


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def _join(toks: list[str]) -> str:
    out = ""
    for t in toks:
        if out and not (_CJK.match(t) and _CJK.match(out[-1])):
            out += " "
        out += t
    return out


def word_changes(before: str, after: str, *, limit: int = 200) -> list[dict]:
    a, b = tokens(before), tokens(after)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out: list[dict] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        out.append({"op": op, "before": _join(a[i1:i2]), "after": _join(b[j1:j2]),
                    "context": _join(a[max(0, i1 - 8):i1])})
        if len(out) >= limit:
            break
    return out


def diff_sections(before: dict[str, str] | None, after: dict[str, str]) -> list[dict]:
    """Changed sections, in section order. ``before=None`` (first snapshot) → no changes."""
    if before is None:
        return []
    keys = sorted(set(before) | set(after), key=_order)
    out: list[dict] = []
    for key in keys:
        old, new = before.get(key), after.get(key)
        if old is not None and new is not None and normalize(old) == normalize(new):
            continue
        out.append({"section": key,
                    "before": (old or "")[:MAX_TEXT] if old is not None else None,
                    "after": (new or "")[:MAX_TEXT] if new is not None else None,
                    "changes": word_changes(old or "", new or "")})
    return out


def _order(key: str):
    prefix, _, rest = key.rpartition(":")
    parts = re.findall(r"\d+", rest or key)
    return (prefix, [int(p) for p in parts] if parts else [10 ** 6], key)
