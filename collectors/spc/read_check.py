"""PHAROS — read the label databases live, the way the weekly run does, without storing anything (dry run).

The proof that a database is really read from the app's servers: for each module, the products of two watched
ingredients are listed (``discover``) and the first labels of each are read (``snapshot``), and the products
found, the list's gaps, the sections read and each label's date are written out. Nothing is written to the
database and no message is sent; ``replay.yml`` runs it from GitHub and puts the result in the run's summary.
Every line passes through ``redact`` (HPRA's key sits in its search address).

    python -m collectors.spc.read_check [module …]     (default: the European readers of 7 Nov 2026)

The exit status is 1 when a module lists no product for either ingredient or reads none of its labels.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import sys

from collectors.core.archive import Archive
from collectors.core.context import FetchContext, redact
from collectors.spc.sections import missing_core

DEFAULT = ("cbg", "famhp", "aifa", "mpa", "infomed", "hpra", "basg", "lyfja")
INGREDIENTS = (
    {"id": "read-check-ivabradine", "inn_en": "ivabradine", "atc_code": "C01EB17", "terms": {}},
    {"id": "read-check-carvedilol", "inn_en": "carvedilol", "atc_code": "C07AG02", "terms": {}},
)
LABELS = 2                  # labels read per ingredient and module


def check(ctx, name: str) -> tuple[list[str], bool]:
    mod = importlib.import_module(f"collectors.spc.{name}")
    lines = [f"### {mod.SOURCE_ID} ({mod.COUNTRY})"]
    found = read = 0
    for ingredient in INGREDIENTS:
        try:
            listing = mod.discover(ctx, ingredient)
        except Exception as e:  # noqa: BLE001 — the check reports every failure and goes on
            lines.append(f"- {ingredient['inn_en']}: listing failed: {type(e).__name__}: {e}")
            continue
        gaps = getattr(listing, "gaps", None) or []         # read before the copy: a plain list has none
        products = list(listing)
        found += len(products)
        lines.append(f"- {ingredient['inn_en']}: {len(products)} products"
                     + (f"; list not read to its end: {'; '.join(gaps)}" if gaps else ""))
        for p in products[:LABELS]:
            product = dataclasses.asdict(p)
            try:
                snap = mod.snapshot(ctx, product)
            except Exception as e:  # noqa: BLE001
                lines.append(f"  - {p.product_name}: unread: {type(e).__name__}: {e}")
                continue
            if snap is None:
                lines.append(f"  - {p.product_name}: no label")
                continue
            read += 1
            core = missing_core(snap.sections)
            lines.append(f"  - {p.product_name}: {len(snap.sections)} sections, dated {snap.doc_date or 'not dated'}"
                         + (f", missing {', '.join(core)}" if core else ""))
    return [redact(x) for x in lines], bool(found and read)


def main(argv: list[str]) -> int:
    names = argv or list(DEFAULT)
    ctx = FetchContext(None, "spc-read-check", archive=Archive(enabled=False), public_only=True)
    ok = True
    out = ["## Label databases read live"]
    try:
        for name in names:
            lines, good = check(ctx, name)
            ok = ok and good
            out += lines + [""]
            print("\n".join(lines), flush=True)
    finally:
        ctx.close()
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
