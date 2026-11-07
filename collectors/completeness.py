"""PHAROS — the weekly list check: every source's own list against what PHAROS holds (7 Nov 2026).

For every switched-on notice source, its list is read again the way a backfill reads it: every page a paging
reader has (GOV.UK's search, EMA's tables), with the same parser and filters as the collection. Nothing is
stored or archived, and no message is sent. Every listed notice is then looked for among the stored ones:

* **stored**: PHAROS holds it (under its own id, or one of the ids a reader also files it under);
* **older**: published before the kept history (``app_setting.backfill_months``; EMA's ``backfill_all``
  sources keep all of it), so not stored on purpose;
* **missing**: listed, inside the kept history, and not stored. Each one is named on the Sources screen.

What a source's filters leave out never reaches the list (it is kept in ``filtered_item``, 0074) and is
counted apart. A mailbox (it lists only unread mail), literature and the label databases are not lists of
notices and are not checked. A list that could not be read whole says so, and its result is not taken as
complete. Until 7 Nov 2026 this was checked by hand (MHRA, EMA, BfArM, MFDS).

One row per source goes to ``list_check`` (0096). Run: ``python -m collectors.completeness`` (audit.yml,
Sunday after the matching audit).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from datetime import date
from typing import Any, Callable

from collectors import backfill as bf
from collectors.core.registry import load_parser, source_configs
from collectors.core.context import redact
from collectors.matching import Matcher
from collectors.parsers import base as parser_base

log = logging.getLogger("collectors.completeness")

MAX_NAMED = 20              # missing notices named per source for an admin
BUDGET_S = 50 * 60          # no new source is read after this (the job's limit is 60 minutes)


def checked(src) -> bool:
    """A source whose list is a list of notices: switched on, not a mailbox, literature or a label database."""
    return src.enabled and src.kind not in ("literature", "spc") and src.channel != "email"


def compare(items: list, known: set[str], src, start: date, aliases: Callable[[Any], list[str]]) -> dict:
    """The listed notices against the stored ids: how many are stored, older than the kept history, missing."""
    listed: dict[str, Any] = {}
    for it in items:
        listed.setdefault(it.external_id, it)
    stored = older = 0
    missing: list[Any] = []
    for eid, it in listed.items():
        if eid in known or any(a in known for a in aliases(it)):
            stored += 1
        elif not bf.in_window(it, src, start):
            older += 1
        else:
            missing.append(it)
    missing.sort(key=lambda it: (it.published or date.min), reverse=True)
    return {"listed": len(listed), "stored": stored, "older": older, "missing": len(missing),
            "missing_items": [{"external_id": it.external_id, "title": (it.title or "")[:300], "url": it.url,
                               "published": it.published.isoformat() if it.published else None}
                              for it in missing[:MAX_NAMED]]}


def check_source(store: Any, ctx: Any, src, start: date, watched: Callable[[str], bool],
                 loader=load_parser) -> dict:
    row = {"source_id": src.id, "listed": 0, "stored": 0, "older": 0, "missing": 0, "filtered": 0,
           "missing_items": [], "complete": True, "error": None}
    parser_base.WATCHED = watched
    parser_base.DROPPED.clear()
    ctx.list_errors = []
    ctx.held_back = 0
    try:
        if hasattr(ctx, "begin_source"):
            ctx.begin_source()
        module = loader(src.parser)
        items = module.list_items(ctx, src)
        row.update(compare(items, store.known_external_ids(src.id), src, start,
                           getattr(module, "aliases", lambda _: [])))
        row["filtered"] = len(dict(parser_base.DROPPED))
        broken = list(getattr(ctx, "list_errors", None) or [])
        if broken:
            row["complete"] = False
            row["error"] = redact(f"{len(broken)} part(s) of the list could not be read; first: {broken[0]}")[:500]
    except Exception as exc:  # noqa: BLE001 - one source's list never stops the others
        row["complete"] = False
        row["error"] = redact(f"{type(exc).__name__}: {exc}")[:500]
        log.warning("%s: list not read: %s", src.id, redact(traceback.format_exc()))
    finally:
        parser_base.WATCHED = None
        parser_base.DROPPED.clear()
    return row


def run(store: Any, ctx: Any, *, sources: list | None = None, loader=load_parser, clock=time.monotonic,
        budget_s: float = BUDGET_S) -> list[dict]:
    settings = store.settings()
    start = bf.cutoff(settings)
    matcher = Matcher(store.load_terms())

    def watched(text: str) -> bool:
        return any(h.term.ingredient_id for h in matcher.match_text(text, "title"))

    t0 = clock()
    rows = []
    for src in [s for s in (sources if sources is not None else source_configs(store)) if checked(s)]:
        if clock() - t0 >= budget_s:
            rows.append({"source_id": src.id, "listed": 0, "stored": 0, "older": 0, "missing": 0, "filtered": 0,
                         "missing_items": [], "complete": False, "error": "not checked this week: out of time"})
            continue
        rows.append(check_source(store, ctx, src, start, watched, loader))
    store.record_list_check(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m collectors.completeness", description=__doc__.split("\n\n")[0]
                            ).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.core.archive import Archive
    from collectors.core.context import FetchContext
    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    try:
        store = Store(db)
        months = int(store.settings().get("backfill_months", 12) or 12)
        # backfill: a paging reader reads its whole list; dry run and no archive: nothing is stored
        with FetchContext(db, "list-check", backfill=True, archive=Archive(enabled=False), dry_run=True,
                          public_only=True) as ctx:
            ctx.store = store
            ctx.watchlist = [r["inn_en"] for r in store.active_ingredients()]
            ctx.backfill_months = months
            out = run(store, ctx)
    finally:
        db.close()
    for r in out:
        log.info("%s: %d listed, %d stored, %d older than the kept history, %d missing, %d filtered%s",
                 r["source_id"], r["listed"], r["stored"], r["older"], r["missing"], r["filtered"],
                 f" ({r['error']})" if r["error"] else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
