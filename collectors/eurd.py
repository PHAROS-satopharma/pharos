"""PHAROS — the EMA EURD list: when each watched ingredient's next PSUR is due.

The List of Union reference dates and frequency of submission of PSURs (EURD list) is one Excel file EMA
republishes about monthly. This reads it, keeps the original in the archive, and stores the rows that
name a watched ingredient (alone or in a combination) in ``eurd_entry``: the frequency, the data lock
point (DLP), the submission date, the next DLP for frequencies under a year, whether generics must submit
PSURs, and the procedure number. The readiness line on the Ingredients page and the weekly report read
them (ingredient_readiness, migration 0045): PSUR frequency, data lock point and submission date.

Run once a day with the daily collection. The list is matched against today's watched ingredients on every
run, and the stored rows are replaced only when the list (its SHA-256) or what it gives the watched ingredients
changed. Until 6 Nov 2026 a list already stored was not read again, so an ingredient added after EMA's last
list had no PSUR dates (and read "not on the EURD list") until EMA published the next one.

    python -m collectors.eurd            # read the list and store the watched rows
    python -m collectors.eurd --file x   # read a saved copy instead (no network)
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import sys
from datetime import date, datetime

log = logging.getLogger("collectors.eurd")

URL = ("https://www.ema.europa.eu/en/documents/other/"
       "list-union-reference-dates-frequency-submission-periodic-safety-update-reports-psurs_en.xlsx")
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Columns of the list, in order, from its header row (the row whose first cell is "ID").
COLUMNS = ("eurd_id", "substance", "eurd", "frequency", "dlp", "submission_date", "next_dlp",
           "next_submission_date", "generics_psur_required", "published", "notes", "procedure",
           "next_procedure", "prac_rapporteur", "lead_ms", "cap", "nap")
DATES = {"dlp", "submission_date", "next_dlp", "next_submission_date", "published"}


def _day(value) -> date | None:
    """A dd/mm/yyyy cell (or an Excel date) as a date; anything else (blank, "Not available*") as None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    m = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*", str(value or ""))
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def _text(value) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def parse(content: bytes) -> tuple[dict, list[dict]]:
    """Return ``({"version", "list_date"}, rows)`` from the EURD workbook's first sheet."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        meta: dict = {"version": None, "list_date": None}
        rows: list[dict] = []
        header_seen = False
        for raw in ws.iter_rows(values_only=True):
            cells = list(raw) + [None] * (len(COLUMNS) - len(raw))
            first = cells[0]
            if not header_seen:
                if isinstance(first, (datetime, date)) and meta["list_date"] is None:
                    meta["list_date"] = _day(first)
                elif isinstance(first, str) and re.match(r"EMA/\d+/\d+", first) and meta["version"] is None:
                    meta["version"] = first.strip()
                elif _day(first) and meta["list_date"] is None:
                    meta["list_date"] = _day(first)
                if isinstance(first, str) and first.strip() == "ID":
                    header_seen = True
                continue
            if first is None or not str(first).strip().isdigit():
                continue
            row = {}
            for name, value in zip(COLUMNS, cells[: len(COLUMNS)], strict=True):
                row[name] = _day(value) if name in DATES else _text(value)
            row["eurd_id"] = int(str(first).strip())
            req = (row["generics_psur_required"] or "").lower()
            row["generics_psur_required"] = True if req.startswith("yes") else False if req.startswith("no") else None
            rows.append(row)
        if not header_seen:
            raise ValueError("the EURD list has no header row starting with ID")
        return meta, rows
    finally:
        wb.close()


def _words(s: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", s.lower()).strip() + " "


def match(rows: list[dict], ingredients: list[dict]) -> list[dict]:
    """The rows that name a watched ingredient as one of their substances, each with ``ingredient_id``
    and ``combination`` (more than one substance). Matching is on whole words, so "ibuprofen" never
    matches "dexibuprofen", and never on what a row excludes ("all combinations with deanol except for
    diclofenac" is not a diclofenac row)."""
    out = []
    for row in rows:
        parts = [re.split(r"\bexcept\b", p, maxsplit=1, flags=re.I)[0].strip()
                 for p in (row["substance"] or "").split("/")]
        parts = [p for p in parts if p]
        for ing in ingredients:
            name = _words(ing["inn_en"])
            if any(name in _words(p) for p in parts):
                out.append({**row, "ingredient_id": ing["id"], "combination": len(parts) > 1})
    return out


def store(db, meta: dict, matched: list[dict], *, sha: str, r2_key: str) -> int:
    """Replace the stored rows with this list's, in one transaction; return how many were stored."""
    with db.transaction():
        db.execute("delete from eurd_entry")
        for r in matched:
            db.execute(
                """insert into eurd_entry (eurd_id, ingredient_id, substance, combination, eurd, frequency, dlp,
                     submission_date, next_dlp, next_submission_date, generics_psur_required, published, notes,
                     procedure, next_procedure, prac_rapporteur, lead_ms, cap, nap, list_version, list_date,
                     sha256, r2_key)
                   values (%(eurd_id)s, %(ingredient_id)s, %(substance)s, %(combination)s, %(eurd)s, %(frequency)s,
                     %(dlp)s, %(submission_date)s, %(next_dlp)s, %(next_submission_date)s, %(generics_psur_required)s,
                     %(published)s, %(notes)s, %(procedure)s, %(next_procedure)s, %(prac_rapporteur)s, %(lead_ms)s,
                     %(cap)s, %(nap)s, %(list_version)s, %(list_date)s, %(sha256)s, %(r2_key)s)""",
                {**r, "list_version": meta["version"] or "unknown", "list_date": meta["list_date"],
                 "sha256": sha, "r2_key": r2_key},
            )
    return len(matched)


def refresh(db, content: bytes, sha: str, put) -> int | None:
    """Match the list against the active ingredients and store the result when it differs from what is stored
    (another list, an ingredient added, watched again or retired); return how many rows were stored, or None
    when nothing changed. ``put(content, mime)`` archives the list and returns ``(…, r2_key)``."""
    meta, rows = parse(content)
    ingredients = db.fetchall("select id::text as id, inn_en from ingredient where active")
    matched = match(rows, ingredients)
    stored = db.fetchall("select eurd_id, ingredient_id::text as ingredient_id, sha256 from eurd_entry")
    pairs = {(int(r["eurd_id"]), str(r["ingredient_id"])) for r in stored}
    if (all(r["sha256"] == sha for r in stored)
            and pairs == {(int(m["eurd_id"]), str(m["ingredient_id"])) for m in matched}):
        return None
    _, key = put(content, MIME)
    return store(db, meta, matched, sha=sha, r2_key=key)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.eurd", description=__doc__.split("\n\n")[0])
    p.add_argument("--file", help="read this saved copy instead of downloading the list")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.core.archive import Archive, sha256_hex
    from collectors.core.db import Db

    if args.file:
        with open(args.file, "rb") as fh:
            content = fh.read()
    else:
        import httpx

        res = httpx.get(URL, follow_redirects=True, timeout=60,
                        headers={"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"})
        res.raise_for_status()
        content = res.content
    sha = sha256_hex(content)
    db = Db()
    try:
        n = refresh(db, content, sha, Archive().put)
        if n is None:
            log.info("EURD list unchanged (%s) and the watched ingredients' rows with it; nothing to do", sha[:12])
        else:
            log.info("EURD list %s: %d row(s) stored for the watched ingredients", sha[:12], n)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
