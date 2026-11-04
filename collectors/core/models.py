"""Data classes every parser and the runner share (binding: docs/CONTRACTS.md)."""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

# The doc_type enum in supabase/migrations/0001_core.sql.
DOC_TYPES = frozenset({
    "dhpc", "safety_alert", "safety_update", "recall", "psusa", "label_change",
    "signal", "newsletter", "literature", "other",
})

SOURCE_KINDS = frozenset({"safety", "recall", "spc", "literature"})
SOURCE_CHANNELS = frozenset({"rss", "atom", "json", "api", "html", "browser", "email"})
SOURCE_SCHEDULES = frozenset({"4h", "12h", "daily", "weekly", "monthly"})


@dataclass
class Item:
    external_id: str              # stable id from the source (guid, url, procedure no.)
    url: str                      # the notice on the regulator's own site
    title: str                    # original language, exactly as published — never translated
    published: date | None
    doc_type: str                 # one of DOC_TYPES
    lang: str | None              # BCP-47 of this item (a source can publish in several)
    body_text: str | None = None  # text of the notice page, if known
    attachment_urls: list[str] = field(default_factory=list)
    structured: dict | None = None  # raw structured fields, stored in document.structured

    def __post_init__(self) -> None:
        if self.doc_type not in DOC_TYPES:
            raise ValueError(f"unknown doc_type {self.doc_type!r}")


@dataclass
class SourceConfig:  # one entry of sources.yaml (and of the source table)
    id: str
    regulator_id: str
    kind: str
    channel: str
    url: str
    parser: str
    languages: list[str]
    schedule: str
    enabled: bool
    options: dict
    expected_max_gap_days: int | None

    @property
    def lang(self) -> str | None:
        """The source's primary language (first listed), or the `lang` option when set."""
        return self.options.get("lang") or (self.languages[0] if self.languages else None)


# ───────────────────────────── charset handling ─────────────────────────────

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_XML_DECL = re.compile(rb"""^\s*<\?xml[^>]*encoding\s*=\s*["']([A-Za-z0-9_.:-]+)["']""", re.I)
_HTTP_CHARSET = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9_.:-]+)", re.I)

# Superset codecs: what servers label shift_jis/euc-kr/latin-1 is almost always the wider Windows set.
_WIDER = {"shift_jis": "cp932", "sjis": "cp932", "x-sjis": "cp932", "euc-kr": "cp949",
          "ks_c_5601-1987": "cp949", "iso-8859-1": "cp1252", "latin-1": "cp1252", "us-ascii": "cp1252"}


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    name = name.strip().strip("\"'").lower()
    name = _WIDER.get(name, name)
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def _try(content: bytes, enc: str) -> str | None:
    try:
        return content.decode(enc)
    except (UnicodeDecodeError, LookupError):
        return None


def _non_ascii(s: str) -> list[str]:
    return [c for c in s if ord(c) > 127]


def _looks_korean(s: str) -> bool:
    chars = _non_ascii(s)
    if len(chars) < 4:
        return False
    hangul = sum(1 for c in chars if "가" <= c <= "힣")
    return hangul / len(chars) >= 0.5


def _looks_japanese(s: str) -> bool:
    chars = _non_ascii(s)
    if len(chars) < 4:
        return False
    kana = sum(1 for c in chars if "぀" <= c <= "ヿ")
    cjk = sum(1 for c in chars if "一" <= c <= "鿿" or "　" <= c <= "〿")
    # Western bytes mis-decoded as Shift_JIS give stray kanji but almost never kana.
    return kana / len(chars) >= 0.15 and (kana + cjk) / len(chars) >= 0.6


def decode_bytes(content: bytes, content_type: str | None = "") -> str:
    """Decode a response: HTTP charset, BOM, meta/XML declaration, then utf-8/euc-kr/shift_jis/cp1252."""
    if not content:
        return ""
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
                     (codecs.BOM_UTF16_BE, "utf-16")):
        if content.startswith(bom):
            text = _try(content, enc)
            if text is not None:
                return text
    declared: list[str] = []
    m = _HTTP_CHARSET.search(content_type or "")
    if m:
        declared.append(m.group(1))
    head = content[:4096]
    for rx in (_XML_DECL, _META_CHARSET):
        m2 = rx.search(head)
        if m2:
            declared.append(m2.group(1).decode("ascii", "ignore"))
    for name in declared:
        enc = _codec(name)
        if enc:
            text = _try(content, enc)
            if text is not None:
                return text
    text = _try(content, "utf-8")
    if text is not None:
        return text
    text = _try(content, "cp949")
    if text is not None and _looks_korean(text):
        return text
    text = _try(content, "cp932")
    if text is not None and _looks_japanese(text):
        return text
    text = _try(content, "euc_jp")
    if text is not None and _looks_japanese(text):
        return text
    return content.decode("cp1252", errors="replace")


@dataclass
class Fetched:
    status: int
    final_url: str
    content: bytes
    content_type: str
    # Filled by FetchContext when the response was archived (status 200).
    sha256: str | None = None
    r2_key: str | None = None

    @cached_property
    def text(self) -> str:
        """Decoded using the HTTP charset, meta charset, then utf-8/cp1252/shift_jis/euc-kr sniffing."""
        return decode_bytes(self.content, self.content_type)

    @property
    def mime(self) -> str:
        return (self.content_type or "application/octet-stream").split(";")[0].strip().lower()

    @property
    def is_pdf(self) -> bool:
        return self.mime == "application/pdf" or self.content[:5] == b"%PDF-"

    @property
    def is_html(self) -> bool:
        return "html" in self.mime

    def json(self):
        import json
        return json.loads(self.text)
