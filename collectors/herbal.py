"""PHAROS — EMA's herbal substances (the HMPC list), kept in ``herbal_substance`` (migration 0111).

The Ingredients screen finds a herbal substance ("ivy leaves", "Hederae helicis folium", "Hedera helix") by the
names in EMA's herbal list. Until 11 November 2026 the lookup read that list from EMA's website at the moment
someone typed, and EMA's site answered it with "429 Too Many Requests", so no herbal could be added. This reads the
list once a day with the collection and replaces the stored rows; the lookup reads them from the database.

A list that comes back short (under MIN_ROWS herbal substances) is not stored: the rows already there stay.

    python -m collectors.herbal            # read EMA's list and store it
    python -m collectors.herbal --file x   # read a saved copy instead (no network)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

log = logging.getLogger("collectors.herbal")

URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-herbal_medicines-report-output-json_en.json"
MIN_ROWS = 50   # EMA lists a few hundred; fewer than this is a broken file, never a list to store


def _text(value) -> str:
    return str(value).strip() if value is not None else ""


def parse(content: bytes) -> list[dict]:
    """The single herbal substances for human use: ``{"name", "latin", "botanical"}``, one per name.

    A combination of several herbs is not one ingredient and is left out, as the lookup always did.
    """
    data = json.loads(content)
    rows = (data.get("data") or []) if isinstance(data, dict) else []
    out: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("category") and row.get("category") != "Human":
            continue
        name, latin = _text(row.get("english_common_name")), _text(row.get("latin_name"))
        if not name or not latin or row.get("combination") == "Yes" or len(name) > 80:
            continue
        out.setdefault(name.lower(), {"name": name, "latin": latin, "botanical": _text(row.get("botanical_name"))})
    return list(out.values())


def store(db, rows: list[dict]) -> int:
    """Replace the stored herbal substances with these, in one transaction; return how many were stored."""
    if len(rows) < MIN_ROWS:
        raise ValueError(f"EMA's herbal list has {len(rows)} single substances (under {MIN_ROWS}); not stored")
    with db.transaction():
        db.execute("delete from herbal_substance")
        for r in rows:
            db.execute(
                "insert into herbal_substance (name, latin, botanical) values (%(name)s, %(latin)s, %(botanical)s)"
                " on conflict (name) do update set latin = excluded.latin, botanical = excluded.botanical,"
                " loaded_at = now()",
                r,
            )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.herbal", description=__doc__.split("\n\n")[0])
    p.add_argument("--file", help="read this saved copy instead of downloading the list")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.file:
        with open(args.file, "rb") as fh:
            content = fh.read()
    else:
        import httpx

        res = httpx.get(URL, follow_redirects=True, timeout=60,
                        headers={"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"})
        res.raise_for_status()
        content = res.content

    rows = parse(content)
    from collectors.core.db import Db

    db = Db()
    try:
        n = store(db, rows)
    finally:
        db.close()
    log.info("EMA herbal list: %d single herbal substances stored", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
