"""PHAROS — the matching audit, every week (6 Nov 2026).

Two questions, per watched ingredient, over every stored notice (not labels or literature):

* **Does a notice name it without being linked to it?** Its own words — the INN in every language, its salts,
  brands and codes — are looked for in the database first (title, structured fields, kept text), so no notice's
  text is downloaded just to look; the matcher then decides, with the same rules as the collection. A notice it
  finds but that is not linked to the ingredient is linked now, as history (no message), the way the check of the
  past links it (collectors/rematch.py ``record``). A word already matched on a notice is never counted again:
  someone who unlinked an ingredient by hand keeps that decision. The audit of 6 Nov 2026 found 48 such notices,
  all older than the 12 months the check of the past then reached.
* **Does a stored name belong to another substance?** An English synonym or brand a lookup proposed (Wikidata,
  PubChem) that RxNorm resolves only to other ingredients ("Ofloxacin" on levofloxacin, 6 Nov 2026) is flagged
  on the Ingredients screen. It is never removed here: an admin removes it.

One row per ingredient goes to ``match_audit`` (0075); the Ingredients screen shows the latest.
Run: ``python -m collectors.match_audit`` (audit.yml, Sunday before the weekly report).
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from collectors.matching import Matcher
from collectors.rematch import Texts, kept_texts, match_document, record, structured_fields

log = logging.getLogger("collectors.match_audit")

BATCH = 50
MAX_LEFT_OVER = 20      # notices listed per ingredient for an admin


def own_words(terms: list) -> list[str]:
    """The texts the database looks for: a code is looked for whole, a word by its own spelling."""
    return sorted({t.term.strip() for t in terms if len(t.term.strip()) >= 3})


def unlinked(doc: dict, hits: list) -> set[str]:
    """The ingredients a notice names but is not linked to (its issue does not carry them, or it has none)."""
    linked = set((doc.get("issue") or {}).get("ingredients") or ())
    return {h.term.ingredient_id for h in hits if h.term.ingredient_id} - linked


def flag_names(rows: list[dict], rxnav: Any) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """Per ingredient, the names RxNorm gives only to other ingredients, and how many could not be checked."""
    flagged: dict[str, list[dict]] = {}
    unchecked: dict[str, int] = {}
    own: dict[str, set[str]] = {}
    for r in rows:
        try:
            # the stored code with its ingredients: levofloxacin was stored as 1546009, "levofloxacin anhydrous"
            # (a precise form), while its names resolve to the ingredient 82122 (7 November 2026)
            stored = str(r["rxcui"])
            if stored not in own:
                own[stored] = {stored} | {c["rxcui"] for c in rxnav.ingredients(stored) if c.get("tty") in (None, "IN")}
            found: dict[str, str] = {}
            for code in rxnav.by_name(r["term"]):
                for c in rxnav.ingredients(code):
                    if c.get("tty") in (None, "IN"):
                        found[c["rxcui"]] = c["name"]
        except Exception as exc:
            # the run logs are public: the name by its id, and no error text (it can carry the name)
            log.warning("%s: RxNorm could not check name %s (%s)", r["ingredient_id"], r["id"], type(exc).__name__)
            unchecked[r["ingredient_id"]] = unchecked.get(r["ingredient_id"], 0) + 1
            continue
        if found and not own[stored] & found.keys():
            flagged.setdefault(r["ingredient_id"], []).append(
                {"term_id": r["id"], "term": r["term"], "why": "RxNorm: " + ", ".join(sorted(found.values()))})
    return flagged, unchecked


def run(store: Any, rxnav: Any = None, *, fields=structured_fields) -> list[dict]:
    terms = store.audit_terms()
    by_ingredient: dict[str, list] = {}
    for t in terms:
        by_ingredient.setdefault(t.ingredient_id, []).append(t)
    rows = {g: {"ingredient_id": g, "names_checked": len(ts), "notices_named": 0, "unlinked_found": 0,
                "linked_now": 0, "left_over": [], "flagged_names": [], "unchecked_names": 0}
            for g, ts in by_ingredient.items()}
    matcher = Matcher(terms)
    class_ingredients = store.class_ingredients()
    ids = store.audit_candidates(own_words(terms))
    log.info("%d notices contain one of %d words of %d ingredients", len(ids), len(terms), len(rows))
    for k in range(0, len(ids), BATCH):
        for doc in store.audit_documents(ids[k:k + BATCH]):
            texts = kept_texts(doc) or Texts()
            every = match_document(matcher, {**doc, "matched_terms": set()}, texts, fields)
            for g in {h.term.ingredient_id for h in every if h.term.ingredient_id}:
                rows[g]["notices_named"] += 1
            hits = match_document(matcher, doc, texts, fields)
            missing = unlinked(doc, hits)
            if not missing:
                continue
            for g in missing:
                rows[g]["unlinked_found"] += 1
            with store.transaction():
                record(store, doc, texts, [h for h in hits if h.term.ingredient_id in missing], class_ingredients)
            # what record() could not link (a notice merge_document keeps out) is listed for an admin
            after = (store.audit_documents([doc["id"]]) or [doc])[0]
            still = missing - set((after.get("issue") or {}).get("ingredients") or ())
            for g in missing:
                if g in still:
                    if len(rows[g]["left_over"]) < MAX_LEFT_OVER:
                        rows[g]["left_over"].append({"document_id": doc["id"], "title": doc.get("title_orig")})
                else:
                    rows[g]["linked_now"] += 1
    if rxnav is not None:
        flagged, unchecked = flag_names(store.audit_names(), rxnav)
        for g, names in flagged.items():
            if g in rows:
                rows[g]["flagged_names"] = names
        for g, n in unchecked.items():
            if g in rows:
                rows[g]["unchecked_names"] = n
    out = list(rows.values())
    store.record_match_audit(out)
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m collectors.match_audit", description=__doc__.split("\n\n")[0]
                            ).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.coding.drugs import RxNav
    from collectors.core.db import Db
    from collectors.core.store import Store

    db = Db()
    try:
        out = run(Store(db), RxNav())
    finally:
        db.close()
    for r in out:
        log.info("%s: %d notices name it, %d were not linked, %d linked now, %d left over, %d names flagged",
                 r["ingredient_id"], r["notices_named"], r["unlinked_found"], r["linked_now"], len(r["left_over"]),
                 len(r["flagged_names"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
