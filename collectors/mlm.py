"""PHAROS — EMA's medical literature monitoring (MLM): which watched ingredients EMA screens itself.

EMA monitors selected literature for a list of substance groups and enters the individual case reports it
finds into EudraVigilance. For a substance on that list, a marketing-authorisation holder does not report to
EudraVigilance the cases from the literature EMA monitors; for any other substance the holder must. This
reads EMA's list (one Excel file, ``ID / Substance Group / Substances``), keeps the original in the archive,
and stores in ``mlm_entry`` the group of each watched ingredient: a group named after it, or the group in
which it appears alone. A watched ingredient with no row is not covered. The case-report flag on literature
notices reads it.

Run once a day with the daily collection. The list is matched against today's watched ingredients on every
run, and the stored rows are replaced only when the list (its SHA-256) or what it gives the watched ingredients
changed. Until 6 Nov 2026 it ran weekly and a list already stored was not read again, so an ingredient added
after EMA's last list read "not monitored by EMA" (its literature cases looking like ours to report) until EMA
published the next one, which can take months.

    python -m collectors.mlm            # read the list and store the watched rows
    python -m collectors.mlm --file x   # read a saved copy instead (no network)
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import sys

log = logging.getLogger("collectors.mlm")

PAGE = ("https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
        "pharmacovigilance-post-authorisation/medical-literature-monitoring")
HOST = "https://www.ema.europa.eu"
MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_LINK = re.compile(r'href="(/en/documents/other/medical-literature-monitoring-substance-groups[^"]+\.xlsx)"')


def _norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def parse(content: bytes) -> list[dict]:
    """``[{group_id, group_name, substances}]`` from the substance-group sheet (herbal groups are left out)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows, header = [], False
        for raw in ws.iter_rows(values_only=True):
            cells = list(raw[:3]) + [None] * (3 - len(raw[:3]))
            if not header:
                header = [str(c or "").strip().lower() for c in cells] == ["id", "substance group", "substances"]
                continue
            if cells[0] is None or not str(cells[0]).strip().isdigit():
                continue
            rows.append({"group_id": int(str(cells[0]).strip()), "group_name": str(cells[1] or "").strip(),
                         "substances": str(cells[2] or "").strip()})
        if not header:
            raise ValueError("the MLM list has no header row ID / Substance Group / Substances")
        return rows
    finally:
        wb.close()


def match(rows: list[dict], ingredients: list[dict]) -> list[dict]:
    """One row per watched ingredient that EMA monitors: its group, and whether the group bears its name.
    A combination that merely contains the ingredient does not count."""
    out = []
    for ing in ingredients:
        name = _norm(ing["inn_en"])
        named = next((r for r in rows if _norm(r["group_name"]) == name), None)
        alone = named or next((r for r in rows if _norm(r["substances"]) == name), None)
        if alone:
            out.append({"ingredient_id": ing["id"], "group_id": alone["group_id"],
                        "group_name": alone["group_name"], "named_group": named is not None})
    return out


def store(db, matched: list[dict], *, list_name: str, sha: str, r2_key: str) -> int:
    with db.transaction():
        db.execute("delete from mlm_entry")
        for m in matched:
            db.execute(
                """insert into mlm_entry (ingredient_id, group_id, group_name, named_group, list_name, sha256, r2_key)
                   values (%(ingredient_id)s, %(group_id)s, %(group_name)s, %(named_group)s, %(list_name)s,
                           %(sha256)s, %(r2_key)s)""",
                {**m, "list_name": list_name, "sha256": sha, "r2_key": r2_key})
    return len(matched)


def refresh(db, content: bytes, sha: str, list_name: str, put) -> int | None:
    """Match the list against the active ingredients and store the result when it differs from what is stored
    (another list, an ingredient added, watched again or retired); return how many rows were stored, or None
    when nothing changed. ``put(content, mime)`` archives the list and returns ``(…, r2_key)``."""
    rows = parse(content)
    ingredients = db.fetchall("select id::text as id, inn_en from ingredient where active")
    matched = match(rows, ingredients)
    stored = db.fetchall("select ingredient_id::text as ingredient_id, group_id, sha256 from mlm_entry")
    pairs = {(str(r["ingredient_id"]), int(r["group_id"])) for r in stored}
    if (all(r["sha256"] == sha for r in stored)
            and pairs == {(str(m["ingredient_id"]), int(m["group_id"])) for m in matched}):
        return None
    _, key = put(content, MIME)
    return store(db, matched, list_name=list_name, sha=sha, r2_key=key)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.mlm", description=__doc__.split("\n\n")[0])
    p.add_argument("--file", help="read this saved copy instead of downloading the list")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.core.archive import Archive, sha256_hex
    from collectors.core.db import Db

    if args.file:
        with open(args.file, "rb") as fh:
            content = fh.read()
        list_name = args.file.replace("\\", "/").rsplit("/", 1)[-1]
    else:
        import httpx

        headers = {"User-Agent": "PHAROS pharmacovigilance monitor (Sato Pharma)"}
        page = httpx.get(PAGE, follow_redirects=True, timeout=60, headers=headers)
        page.raise_for_status()
        link = _LINK.search(page.text)
        if not link:
            raise RuntimeError("the MLM page links no substance-group list")
        res = httpx.get(HOST + link.group(1), follow_redirects=True, timeout=60, headers=headers)
        res.raise_for_status()
        content, list_name = res.content, link.group(1).rsplit("/", 1)[-1]
    sha = sha256_hex(content)
    db = Db()
    try:
        n = refresh(db, content, sha, list_name, Archive().put)
        if n is None:
            log.info("MLM list %s unchanged and the watched ingredients' rows with it; nothing to do", list_name)
        else:
            log.info("MLM list %s: %d watched ingredient(s) monitored by EMA", list_name, n)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
