"""PHAROS — shared types for the SPC / label watch country modules.

Every module under ``collectors/spc/`` (cima, bdpm, ema_epar, dailymed, mhra, pmda_pi, nedrug, hc_dpd, medsafe)
defines:

* ``SOURCE_ID`` — its ``source`` row (``spc-cima`` …, ``kind: spc``), ``COUNTRY`` and ``LANG``;
* ``discover(ctx, ingredient) -> list[Product]`` — the products authorised for one active
  ingredient (``ingredient`` = ``{"id", "inn_en", "atc_code", "terms": {lang: [term, …]}}``). A module
  whose list can break off partway (a page, a code or a search term that did not answer) returns a
  ``Listing`` with ``complete`` False: ``run.py`` then switches off no product it did not reach, and
  says so, instead of reading the missing ones as withdrawn;
* ``listed_version(product) -> str | None`` (optional) — the label's version as the regulator's list gives it
  (DailyMed's SPL version, PMDA's package id, CIMA's document date, EMA's last update, MHRA's document id).
  ``run.py`` reads a label whose listed version moved first, and does not read again, for up to
  ``RECHECK_DAYS``, a label whose listed version is the one its last snapshot was read at;
* ``snapshot(ctx, product) -> Snapshot | None`` — the product's current label split into sections
  (``product`` = the ``spc_product`` row as a dict); ``None`` when no label is published. A label
  that could not be read (an HTTP error, a missing section, an unknown shape) raises — never a
  partial snapshot, which would read as removed sections.

A module that can read one label two ways (CIMA: per-section API, else the full HTML) sets
``Snapshot.method``; ``run.py`` diffs a snapshot only against the last one read the same way.

``collectors/spc/run.py`` does the rest (rows, hashes, diffs, issues).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Product:
    national_id: str              # nregistro, CIS, EMEA/H/C/…, setid, PL number, PMDA package id
    product_name: str             # as published
    mah: str | None = None
    url: str | None = None        # the product's page on the regulator's site
    country_code: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Snapshot:
    sections: dict[str, str]      # {"4.4": text, …} in the label's own language
    doc_date: date | None = None  # revision date of the label, when the source gives one
    lang: str | None = None
    source_url: str | None = None  # where the label text was read
    original_sha256: str | None = None  # sha of the archived original (PDF/HTML/XML), if any
    method: str | None = None     # how the sections were read, when a source has more than one way


class SnapshotError(Exception):
    """The label exists but could not be read completely: a failure of that product, not a change."""


class Listing(list):
    """``discover``'s products, and whether the list was read to its end (``gaps``: what was not)."""

    def __init__(self, items=(), *, gaps: list[str] | None = None):
        super().__init__(items)
        self.gaps: list[str] = list(gaps or [])

    @property
    def complete(self) -> bool:
        return not self.gaps


def fetch_label(ctx, url: str, **kwargs: Any):
    """``ctx.get`` for a label, always in full. Two ingredients may share one label (0079); the second
    read in the same run would otherwise be a bare 304, read as "no label text" and never stored for it."""
    if hasattr(ctx, "forget"):
        ctx.forget(url)
    return ctx.get(url, **kwargs)


def run_cache(ctx, name: str) -> dict:
    """A dict that lives as long as ``ctx`` (one run): bulk files read once per run, never longer."""
    caches = getattr(ctx, "_spc_caches", None)
    if caches is None:
        caches = {}
        ctx._spc_caches = caches
    return caches.setdefault(name, {})


def get_reusing(ctx, url: str, **kwargs: Any):
    """``ctx.get``, except that a 304 for a URL already read in this run (the same product found
    for two ingredients) answers the body read the first time instead of an empty one."""
    seen = run_cache(ctx, "bodies")
    f = ctx.get(url, **kwargs)
    if f.status == 200:
        seen[url] = f
    elif f.status == 304 and url in seen:
        return seen[url]
    return f


def terms_for(ingredient: dict, lang: str, *, fallback_en: bool = True) -> list[str]:
    """INN terms of ``ingredient`` in ``lang`` (kind inn first), else the English INN."""
    terms = list((ingredient.get("terms") or {}).get(lang) or [])
    if not terms and fallback_en and ingredient.get("inn_en"):
        terms = [ingredient["inn_en"]]
    seen: set[str] = set()
    out = []
    for t in terms:
        if t and t.casefold() not in seen:
            seen.add(t.casefold())
            out.append(t)
    return out
