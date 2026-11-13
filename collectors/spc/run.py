"""PHAROS — SPC / label watch entry point (``run_spc``), called weekly by ``collectors/run.py``.

For every active ingredient (or the ones given) and every enabled ``kind: spc`` source:

1. **discover** the products authorised in that country (``spc_product``: upsert on
   ``(source_id, ingredient_id, national_id)``; products no longer listed are marked inactive — only when the
   list was read to its end: a ``Listing`` with gaps, or an empty answer where products were listed before,
   switches nothing off and is noted as a partial list, and a discovery that failed still reads the products
   already known). A label
   that holds several watched ingredients (a cold remedy with paracetamol, guaifenesin and phenylephrine)
   is one product per ingredient: until 0079 the first ingredient to list it kept it, and the others never
   saw it (Japan's paracetamol inserts sat under ivabradine, 6 Nov 2026);
2. **snapshot** each active product's label, split into sections in its own language; the section
   texts are archived as one canonical JSON object (``{"sections": {…}}``, sorted keys) whose
   sha256 is the snapshot's ``sha256`` and whose key is its ``r2_key``; ``section_hashes`` holds one
   sha256 per section (``spc_snapshot``);
3. **diff** against the previous snapshot (its section texts are read back from the archive):
   changed sections are diffed word by word (``spc_change.diff``, original language);
4. when a watched section changed (``sections.WATCHED``; section 10 is recorded but never alerts),
   a ``document`` (doc_type ``label_change``) is stored for the new snapshot and an ``issue`` is
   opened with it as anchor, linked to the ingredient; ``spc_change.issue_id`` points at it.

The first snapshot of a product is a baseline: no change, no issue. A snapshot is diffed only
against the last one read the same way (``Snapshot.method``; CIMA reads a label per section or, as
a fallback, from the full HTML); with none, it is a new baseline — unless the label's revision date
moved past the newest snapshot's, when it is compared with that one all the same. Returns the ids of the issues
created, which the runner alerts on.

**Time.** The run's time budget (``PHAROS_TIME_BUDGET_MIN``, the runner's deadline) holds here too: each source
gets an even share of what is left (a source that finishes early leaves its time to the next), and within a
source the labels are read in turn: our reference products first, then labels never read, then the one read
longest ago (``spc_product.checked_at``, 0063). What the time does not reach is read first on the next run, and
the source_run says how many were left; running out of time is never a failed run. Before this (6 Nov 2026)
a week with paracetamol's hundreds of products ran past GitHub's timeout and the run was killed before it
reached Japan.

The weekly watch runs one source per job (``label-watch.yml``, ``python -m collectors.run --spc-source``), so each
source has the whole budget (330 minutes) to itself. Until 13 Nov 2026 the seventeen sources shared one job's
78 minutes, about 4.6 minutes each: on 9 Nov DailyMed, CIMA and the MHRA spent all of it on their product lists
and read no label, and 3,608 of 5,483 labels had never been read.

Every SPC source gets a ``source_run`` row per run (products seen, new snapshots, issues, and the
errors: a discovery or a label that failed, labels with no text), and its health: ``ok`` after a run
that read labels, ``blocked`` on a bot check, ``degraded`` after ``DEGRADED_AFTER`` failed runs in a
row (no discovery answered, or not one label could be read) — the admins get the usual health
alert on the change. (SPC sources have no ``expected_max_gap_days``: labels may rightly stay the
same for years, so quiet is not a symptom; failures are.)

Module per source: spc-cima → cima, spc-bdpm → bdpm, spc-ema-epar → ema_epar,
spc-dailymed → dailymed, spc-mhra → mhra, spc-pmda → pmda_pi, spc-nedrug → nedrug (Korea),
spc-hc-dpd → hc_dpd (Canada), spc-medsafe → medsafe (New Zealand), spc-cbg → cbg (Netherlands),
spc-famhp → famhp (Belgium), spc-aifa → aifa (Italy), spc-mpa → mpa (Sweden), spc-infomed → infomed (Portugal),
spc-hpra → hpra (Ireland), spc-basg → basg (Austria), spc-lyfja → lyfja (Iceland).
"""

from __future__ import annotations

import importlib
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from collectors.core.context import SourceBlocked, redact
from collectors.spc.common import Product, Snapshot
from collectors.spc.diff import diff_sections
from collectors.spc.sections import hashes, normalize, watched_changes

log = logging.getLogger(__name__)

MODULES = {
    "spc-cima": "cima",
    "spc-bdpm": "bdpm",
    "spc-ema-epar": "ema_epar",
    "spc-dailymed": "dailymed",
    "spc-mhra": "mhra",
    "spc-pmda": "pmda_pi",
    "spc-nedrug": "nedrug",
    "spc-hc-dpd": "hc_dpd",
    "spc-medsafe": "medsafe",
    "spc-cbg": "cbg",
    "spc-famhp": "famhp",
    "spc-aifa": "aifa",
    "spc-mpa": "mpa",
    "spc-infomed": "infomed",
    "spc-hpra": "hpra",
    "spc-basg": "basg",
    "spc-lyfja": "lyfja",
}
DEGRADED_AFTER = 2          # failed SPC runs in a row (weekly) before the source is 'degraded'
RECENT_SNAPSHOTS = 10       # how far back a snapshot read the same way is looked for
RECHECK_DAYS = 28           # a label at the version its last snapshot was read at is read again after this


@dataclass
class SpcStats:
    products: int = 0            # products found (items_seen)
    snapshots: int = 0           # new snapshot rows (items_new)
    issues: int = 0              # label-change issues opened (items_matched)
    labels_read: int = 0
    no_label: int = 0            # a label read, but no text in it
    none_published: int = 0      # the regulator publishes no label for the product (the module's None)
    discover_ok: int = 0
    errors: list[str] = field(default_factory=list)
    out_of_time: bool = False
    labels_left: int = 0         # products found but not read this run (out of time)
    revised: int = 0             # labels read first: the regulator lists a new version
    unchanged: int = 0           # labels not read: the regulator lists the version last read, read lately
    ingredients_left: int = 0    # ingredients not even looked up this run (out of time)

    def failed(self, ingredients: int) -> bool:
        """Nothing worked: no discovery answered, or products were found and no label was read.
        Running out of time is not a failure of the source."""
        if self.out_of_time:
            return False
        if ingredients and not self.discover_ok:
            return True
        return self.products > 0 and self.labels_read == 0

    def error_text(self) -> str | None:
        notes = []
        if self.errors:
            notes.append(f"{len(self.errors)} error(s); first: {self.errors[0]}")
        if self.no_label:
            notes.append(f"{self.no_label} product(s) without label text")
        if self.none_published:
            # the same opening as above, so source_run_failed() (0089) and the Sources page read it as a note
            notes.append(f"{self.none_published} product(s) without label text: the regulator publishes none for them")
        if self.out_of_time:
            left = f"{self.labels_left} label(s)"
            if self.ingredients_left:
                left += f" and {self.ingredients_left} ingredient(s)"
            notes.append(f"out of time: {left} left for the next run")
        return redact("; ".join(notes))[:1000] or None


# ───────────────────────────── archive ─────────────────────────────

def canonical(snapshot: Snapshot) -> bytes:
    """The archived form of a snapshot. Only the texts, their language and (when the source has
    more than one) the way they were read go in, so a PDF that is regenerated with identical text
    gives the same sha256 (no new snapshot row)."""
    body = {"sections": {k: snapshot.sections[k] for k in sorted(snapshot.sections)},
            "lang": snapshot.lang}
    if snapshot.method:
        body["method"] = snapshot.method
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


def load_archived(ctx, r2_key: str | None) -> dict | None:
    """``{"sections": {…}, "method": str | None}`` of an archived snapshot, or None if unreadable."""
    if not r2_key:
        return None
    archiver = getattr(ctx, "archiver", None)
    if archiver is None or not hasattr(archiver, "get"):
        return None
    raw = archiver.get(r2_key)
    if not raw:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
        return {"sections": dict(body.get("sections") or {}), "method": body.get("method")}
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None


def load_sections(ctx, r2_key: str | None) -> dict[str, str] | None:
    body = load_archived(ctx, r2_key)
    return body["sections"] if body is not None else None


# ───────────────────────────── database ─────────────────────────────

def _ingredients(db, ids: list[str] | None) -> list[dict]:
    if ids:
        rows = db.fetchall("select id, inn_en, atc_code, rxcui from ingredient where id = any(%(ids)s::uuid[])",
                           {"ids": ids})
    else:
        rows = db.fetchall("select id, inn_en, atc_code, rxcui from ingredient where active order by inn_en")
    for r in rows:
        r["id"] = str(r["id"])
        terms: dict[str, list[str]] = {}
        for t in db.fetchall(
                """select lang, term from ingredient_term where ingredient_id = %(i)s
                   and kind in ('inn','salt','synonym') order by (kind = 'inn') desc, term""",
                {"i": r["id"]}):
            terms.setdefault(t["lang"].split("-")[0], []).append(t["term"])
        r["terms"] = terms
    return rows


def _sources(db) -> list[str]:
    rows = db.fetchall("select id from source where kind = 'spc' and enabled order by id")
    return [r["id"] for r in rows if r["id"] in MODULES]


def upsert_product(db, source_id: str, ingredient_id: str, p: Product) -> dict:
    row = db.fetchone(
        """insert into spc_product (ingredient_id, source_id, country_code, national_id,
             product_name, mah, url, extra, active)
           values (%(ing)s, %(src)s, %(cc)s, %(nid)s, %(name)s, %(mah)s, %(url)s, %(extra)s, true)
           on conflict (source_id, ingredient_id, national_id) do update
             set product_name = excluded.product_name, mah = excluded.mah,
                 url = coalesce(excluded.url, spc_product.url),
                 extra = spc_product.extra || excluded.extra, active = true
           returning id, ingredient_id, source_id, country_code, national_id, product_name, mah,
                     url, extra, is_reference, checked_at""",
        {"ing": ingredient_id, "src": source_id, "cc": p.country_code, "nid": p.national_id,
         "name": p.product_name, "mah": p.mah, "url": p.url, "extra": _json(p.extra or {})})
    out = dict(row)
    out["id"] = str(out["id"])
    out["extra"] = out.get("extra") or p.extra
    return out


def deactivate_missing(db, source_id: str, ingredient_id: str, keep: list[str]) -> None:
    db.execute(
        """update spc_product set active = false
            where source_id = %(s)s and ingredient_id = %(i)s and active
              and not (national_id = any(%(k)s))""",
        {"s": source_id, "i": ingredient_id, "k": keep})


def known_products(db, source_id: str, ingredient_id: str) -> list[dict]:
    """The ingredient's active products from earlier runs: read all the same when this run's list of them
    failed or broke off, so a list that did not answer never leaves their labels unread for the week."""
    rows = db.fetchall(
        """select id, ingredient_id, source_id, country_code, national_id, product_name, mah, url, extra,
                  is_reference, checked_at
             from spc_product where source_id = %(s)s and ingredient_id = %(i)s and active""",
        {"s": source_id, "i": ingredient_id})
    out = []
    for r in rows:
        r = dict(r)
        r["id"] = str(r["id"])
        r["extra"] = r.get("extra") or {}
        out.append(r)
    return out


def mark_checked(db, product_id: str) -> None:
    """The label was read (or has no text): its turn comes round again after every other one, and the error of
    an earlier read that failed is cleared."""
    db.execute("update spc_product set checked_at = now(), last_error = null, last_error_at = null "
               "where id = %(p)s", {"p": product_id})


def mark_unread(db, product_id: str, error: str) -> None:
    """The label could not be read this run: the screen shows it as unread with this error (0091). It is not
    marked read, so it is read first next run."""
    db.execute("update spc_product set last_error = %(e)s, last_error_at = now() where id = %(p)s",
               {"p": product_id, "e": error[:500]})


def record_listing(db, source_id: str, ingredient_id: str, products: int, gaps: list[str]) -> None:
    """The newest list of the ingredient's products from this source, and whether it was read to its end
    (``spc_listing``, 0091): what the screen and the Sources page say about the list."""
    db.execute(
        """insert into spc_listing (source_id, ingredient_id, listed_at, products, complete, gaps)
           values (%(s)s, %(i)s, now(), %(n)s, %(c)s, %(g)s)
           on conflict (source_id, ingredient_id) do update
              set listed_at = excluded.listed_at, products = excluded.products,
                  complete = excluded.complete, gaps = excluded.gaps""",
        {"s": source_id, "i": ingredient_id, "n": products, "c": not gaps,
         "g": redact("; ".join(gaps))[:1000] if gaps else None})


def _turn(product: dict) -> tuple:
    """Reading order within a source: our reference products, then labels the regulator lists at a new version,
    then labels never read, then the oldest read."""
    checked = product.get("checked_at")
    return (not product.get("is_reference"), not product.get("_revised"), checked is not None, checked or "")


def last_versions(db, product_ids: list[str]) -> dict[str, str | None]:
    """The regulator's version each product's newest snapshot was read at (0086)."""
    if not product_ids:
        return {}
    rows = db.fetchall(
        """select distinct on (spc_product_id) spc_product_id, regulator_version from spc_snapshot
            where spc_product_id = any(%(ids)s::uuid[]) order by spc_product_id, fetched_at desc""",
        {"ids": product_ids})
    return {str(r["spc_product_id"]): r.get("regulator_version") for r in rows}


def _recent(checked, days: int = RECHECK_DAYS) -> bool:
    if not isinstance(checked, datetime):
        return False
    when = checked if checked.tzinfo else checked.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - when < timedelta(days=days)


def plan_reads(module, queue: list[tuple[dict, dict]], versions: dict[str, str | None],
               stats: SpcStats) -> list[tuple[dict, dict]]:
    """Mark each product revised (the regulator lists a version other than the one last read) and leave out the
    ones the regulator lists at the version last read, when read within ``RECHECK_DAYS``. A source without
    ``listed_version`` reads every label in turn, as before."""
    listed = getattr(module, "listed_version", None)
    if listed is None:
        return queue
    out = []
    for product, ing in queue:
        now_v, last_v = listed(product), versions.get(product["id"])
        if now_v and last_v and now_v != last_v:
            product["_revised"] = True
            stats.revised += 1
        elif now_v and last_v == now_v and _recent(product.get("checked_at")) and not product.get("is_reference"):
            stats.unchanged += 1
            continue
        out.append((product, ing))
    return out


def last_snapshot(db, product_id: str) -> dict | None:
    return db.fetchone(
        """select id, sha256, r2_key, section_hashes from spc_snapshot
            where spc_product_id = %(p)s order by fetched_at desc limit 1""", {"p": product_id})


def recent_snapshots(db, product_id: str, limit: int = RECENT_SNAPSHOTS) -> list[dict]:
    return db.fetchall(
        """select id, sha256, r2_key, section_hashes, doc_date, regulator_version from spc_snapshot
            where spc_product_id = %(p)s order by fetched_at desc limit %(n)s""",
        {"p": product_id, "n": limit})


def comparable(ctx, rows: list[dict], method: str | None) -> tuple[dict | None, dict | None]:
    """(row, its archived sections) of the newest snapshot read the same way as the new one.

    The newest snapshot whose archive cannot be read is compared by its section hashes, as before
    (``(row, None)``). An older snapshot read another way is skipped; ``(None, None)`` when no
    snapshot was read this way — the new one is then a baseline. A snapshot of an older revision
    than one read since (``doc_date``) is not comparable either: that revision was compared when
    it was read (``revised_since``)."""
    latest: date | None = None
    for i, row in enumerate(rows):
        body = load_archived(ctx, row.get("r2_key"))
        if body is None:
            if i == 0:
                return row, None
        elif body.get("method") == method:
            if latest and row.get("doc_date") and row["doc_date"] < latest:
                return None, None
            return row, body["sections"]
        if row.get("doc_date") and (latest is None or row["doc_date"] > latest):
            latest = row["doc_date"]
    return None, None


def revised_since(ctx, rows: list[dict], snap: Snapshot) -> tuple[dict | None, dict | None]:
    """With no snapshot read the way ``snap`` was: (the newest snapshot, its archived sections) when
    ``snap`` is a later revision of the label (``doc_date``), else (None, None). The texts were read
    another way, so the diff may also show sections that only read differently; a revision
    published while the reading changed must alert all the same, never become the new baseline."""
    if not rows or not snap.doc_date or not rows[0].get("doc_date") or snap.doc_date <= rows[0]["doc_date"]:
        return None, None
    body = load_archived(ctx, rows[0].get("r2_key"))
    return rows[0], (body["sections"] if body is not None else None)


def _json(value: Any):
    try:
        from collectors.core.db import jsonb

        return jsonb(value)
    except ImportError:  # pragma: no cover - fixture tests without the db layer
        return json.dumps(value, ensure_ascii=False)


def change_title(product: dict, sections: list[str]) -> str:
    """The product name as published, then the changed section numbers (no translation)."""
    return f"{product['product_name']} — {', '.join(sections)}"


def record_change(db, ctx, source_id: str, product: dict, ingredient: dict, snap: Snapshot,
                  snap_id: str, prev_id: str | None, sha: str, key: str, size: int,
                  changes: list[dict]) -> str | None:
    """Write spc_change (and, for a watched change, document + issue). -> the issue id or None."""
    sections = [c["section"] for c in changes]
    alerting = watched_changes(sections)
    issue_id: str | None = None
    linked: str | None = None          # an issue the same label already opened for another ingredient
    if alerting:
        title = change_title(product, alerting)
        doc = db.fetchone(
            """insert into document (source_id, external_id, url, title_orig, lang, doc_type,
                 published_date, sha256, r2_key, mime, bytes, extraction, structured, is_backfill)
               values (%(src)s, %(ext)s, %(url)s, %(title)s, %(lang)s, 'label_change', %(pub)s,
                 %(sha)s, %(key)s, 'application/json', %(bytes)s, 'text', %(st)s, false)
               on conflict (source_id, external_id) do nothing returning id""",
            {"src": source_id, "ext": f"spc:{product['national_id']}:{sha[:16]}",
             "url": product.get("url") or snap.source_url or "", "title": title,
             "lang": snap.lang, "pub": snap.doc_date or date.today(), "sha": sha, "key": key,
             "bytes": size,
             "st": _json({"spc_product_id": product["id"], "national_id": product["national_id"],
                          "product_name": product["product_name"], "mah": product.get("mah"),
                          "country_code": product.get("country_code"),
                          "sections": alerting, "all_changed_sections": sections,
                          "source_url": snap.source_url})})
        if doc is None:
            # The same label, read for another of its ingredients, already opened the issue: this ingredient
            # joins it. Not returned, so the change is alerted once.
            shared = db.fetchone(
                """select i.id, d.id as document_id from document d
                     join issue i on i.anchor_document_id = d.id
                    where d.source_id = %(src)s and d.external_id = %(ext)s""",
                {"src": source_id, "ext": f"spc:{product['national_id']}:{sha[:16]}"})
            if shared is not None:
                linked = str(shared["id"])
                db.execute("""insert into issue_ingredient (issue_id, ingredient_id)
                              values (%(i)s, %(g)s) on conflict do nothing""",
                           {"i": linked, "g": ingredient["id"]})
                db.execute(
                    """insert into match (document_id, ingredient_id, field, matched_text, snippet, confidence)
                       select %(d)s, %(g)s, 'structured', %(t)s, %(s)s, 'high'
                        where not exists (select 1 from match
                                           where document_id = %(d)s and ingredient_id = %(g)s)""",
                    {"d": str(shared["document_id"]), "g": ingredient["id"], "t": product["product_name"],
                     "s": f"SPC {', '.join(alerting)}"})
        if doc is not None:
            doc_id = str(doc["id"])
            row = db.fetchone(
                """insert into issue (doc_type, title, anchor_document_id, first_date, class_only,
                     is_backfill) values ('label_change', %(t)s, %(d)s, %(f)s, false, false)
                   returning id""",
                {"t": title, "d": doc_id, "f": snap.doc_date or date.today()})
            issue_id = str(row["id"])
            db.execute("""insert into issue_document (issue_id, document_id, link, method)
                          values (%(i)s, %(d)s, 'anchor', 'auto') on conflict do nothing""",
                       {"i": issue_id, "d": doc_id})
            db.execute("""insert into issue_ingredient (issue_id, ingredient_id)
                          values (%(i)s, %(g)s) on conflict do nothing""",
                       {"i": issue_id, "g": ingredient["id"]})
            db.execute(
                """insert into match (document_id, ingredient_id, field, matched_text, snippet,
                     confidence) values (%(d)s, %(g)s, 'structured', %(t)s, %(s)s, 'high')""",
                {"d": doc_id, "g": ingredient["id"], "t": product["product_name"],
                 "s": f"SPC {', '.join(alerting)}"})
    row = db.fetchone(
        """insert into spc_change (spc_product_id, from_snapshot, to_snapshot, sections, diff,
             issue_id) values (%(p)s, %(f)s, %(t)s, %(s)s, %(d)s, %(i)s) returning id""",
        {"p": product["id"], "f": prev_id, "t": snap_id, "s": sections, "d": _json(changes),
         "i": issue_id or linked})
    change_id = str(row["id"]) if row and row.get("id") else None
    if change_id:
        # Our label against this change (label_gap, 0043): the check never loses the change it describes. It
        # runs in its own savepoint: a database error inside it aborts only the check, not the transaction
        # that holds the snapshot, the change and its issue (finding 10 of the 6 Nov 2026 review of #119).
        try:
            from collectors.labels import recompute

            with db.transaction():
                recompute.gap_for_change(db, change_id, ingredient["id"], changes, snap.lang)
        except Exception:  # noqa: BLE001 - the comparison is caught up on the next run
            log.warning("gap check for change %s failed: %s", change_id, traceback.format_exc())
    return issue_id


def watch_product(db, ctx, module, source_id: str, product: dict, ingredient: dict,
                  stats: SpcStats | None = None) -> str | None:
    stats = stats if stats is not None else SpcStats()
    snap = module.snapshot(ctx, product)
    if snap is None:
        # no label published (Health Canada's non-prescription products: "product monograph is not available")
        stats.none_published += 1
        return None
    snap.sections = {k: v for k, v in (snap.sections or {}).items() if normalize(v)}
    if not snap.sections:
        stats.no_label += 1
        return None
    stats.labels_read += 1
    listed = getattr(module, "listed_version", None)
    version = listed(product) if listed else None
    raw = canonical(snap)
    sha, key = ctx.archive(raw, "application/json")
    rows = recent_snapshots(db, product["id"])
    if rows and rows[0].get("sha256") == sha:
        if version and rows[0].get("regulator_version") != version:
            # a new version on the regulator's list with the same text: remember it, so the label is not
            # taken as revised again next week
            db.execute("update spc_snapshot set regulator_version = %(v)s where id = %(i)s",
                       {"v": version, "i": rows[0]["id"]})
        return None
    prev, before = comparable(ctx, rows, snap.method)
    if rows and prev is None:
        prev, before = revised_since(ctx, rows, snap)
        if prev is None:
            log.info("SPC %s %s: first snapshot read as %r; a new baseline, not a change",
                     source_id, product["national_id"], snap.method)
        else:
            log.info("SPC %s %s: read as %r for the first time, and revised (%s): compared with "
                     "the reading before", source_id, product["national_id"], snap.method,
                     snap.doc_date)
    with db.transaction():
        row = db.fetchone(
            """insert into spc_snapshot (spc_product_id, doc_date, sha256, r2_key, section_hashes,
                 regulator_version)
               values (%(p)s, %(d)s, %(s)s, %(k)s, %(h)s, %(v)s) returning id""",
            {"p": product["id"], "d": snap.doc_date, "s": sha, "k": key,
             "h": _json(hashes(snap.sections)), "v": version})
        snap_id = str(row["id"])
        stats.snapshots += 1
        if prev is None:
            return None                        # baseline
        if prev.get("sha256") == sha:
            return None                        # back to the text last read this way
        if before is None:
            # The previous texts are unreadable: compare hashes only, without word diff.
            old_h = prev.get("section_hashes") or {}
            if isinstance(old_h, str):
                old_h = json.loads(old_h)
            new_h = hashes(snap.sections)
            changed = sorted(k for k in set(old_h) | set(new_h) if old_h.get(k) != new_h.get(k))
            changes = [{"section": k, "before": None, "after": snap.sections.get(k),
                        "changes": []} for k in changed]
        else:
            changes = diff_sections(before, snap.sections)
        if not changes:
            return None
        return record_change(db, ctx, source_id, product, ingredient, snap, snap_id,
                             str(prev["id"]), sha, key, len(raw), changes)


def _watch_source(ctx, db, module, source_id: str, ingredients: list[dict], stats: SpcStats,
                  created: list[str], deadline: float | None = None,
                  clock: Callable[[], float] = time.monotonic) -> None:
    """Appends to ``created`` as it goes, so issues opened before a bot check are still alerted.

    Every ingredient's products are found first, then the labels are read in turn (``_turn``) until
    ``deadline`` (a ``clock()`` value); what is left is counted in ``stats`` and read first next time."""
    queue: list[tuple[dict, dict]] = []
    for n, ing in enumerate(ingredients):
        if deadline is not None and clock() >= deadline:
            stats.out_of_time, stats.ingredients_left = True, len(ingredients) - n
            break
        try:
            found = module.discover(ctx, ing)
        except SourceBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - one ingredient failing never stops the rest
            stats.errors.append(redact(f"discover {ing['inn_en']}: {type(exc).__name__}: {exc}"))
            log.warning("SPC %s discover %s: %s", source_id, ing["inn_en"], redact(exc))
            # its products from earlier runs are still read: a list that failed is not a week without labels
            known = known_products(db, source_id, ing["id"])
            record_listing(db, source_id, ing["id"], len(known),
                           [f"the list failed: {type(exc).__name__}: {exc}; {len(known)} listed before kept"])
            stats.products += len(known)
            queue += [(row, ing) for row in known]
            continue
        gaps = list(getattr(found, "gaps", None) or [])
        known = known_products(db, source_id, ing["id"])
        if not found and known:
            # an empty answer where products were listed before is a list that did not answer, not every
            # product withdrawn at once: nothing is switched off, and it is a failed discovery
            gaps.append(f"listed no product; {len(known)} listed before kept")
        if gaps:
            stats.errors.append(redact(f"discover {ing['inn_en']}: partial list: {'; '.join(gaps)}"[:500]))
            log.warning("SPC %s discover %s: partial list (%s); no product switched off", source_id,
                        ing["inn_en"], redact("; ".join(gaps)))
        if found or not known:
            stats.discover_ok += 1
        with db.transaction():
            ids = set()
            for p in found:
                row = upsert_product(db, source_id, ing["id"], p)
                ids.add(row["id"])
                queue.append((row, ing))
            if found and not gaps:
                deactivate_missing(db, source_id, ing["id"], [p.national_id for p in found])
            elif gaps:
                # the products the list did not reach stay active, and their labels are read as usual
                queue += [(row, ing) for row in known if row["id"] not in ids]
        kept = len([r for r in known if r["id"] not in ids]) if gaps else 0
        stats.products += len(found) + kept
        record_listing(db, source_id, ing["id"], len(found) + kept, gaps)
    queue = plan_reads(module, queue, last_versions(db, sorted({p["id"] for p, _i in queue})), stats)
    if stats.revised or stats.unchanged:
        # counts, not errors: the source_run's error column holds only what went wrong
        log.info("SPC %s: %d label(s) revised by the regulator, read first; %d at the version last read, "
                 "not read again", source_id, stats.revised, stats.unchanged)
    queue.sort(key=lambda pair: _turn(pair[0]))      # stable: ingredient and listing order otherwise
    for n, (product, ing) in enumerate(queue):
        if deadline is not None and clock() >= deadline:
            stats.out_of_time, stats.labels_left = True, len(queue) - n
            break
        try:
            issue = watch_product(db, ctx, module, source_id, product, ing, stats)
        except SourceBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, next product; not marked read, so first next time
            stats.errors.append(redact(f"{product['national_id']}: {type(exc).__name__}: {exc}"))
            log.warning("SPC %s %s: %s", source_id, product["national_id"], redact(exc))
            mark_unread(db, product["id"], redact(f"{type(exc).__name__}: {exc}"))
            continue
        mark_checked(db, product["id"])
        if issue:
            stats.issues += 1
            created.append(issue)
    if stats.out_of_time:
        log.info("SPC %s out of time: %d label(s), %d ingredient(s) left for the next run",
                 source_id, stats.labels_left, stats.ingredients_left)


def run_source(ctx, db, store, notifier, source_id: str, ingredients: list[dict],
               deadline: float | None = None, clock: Callable[[], float] = time.monotonic) -> list[str]:
    """One SPC source for every ingredient, with its source_run row and health (see the top)."""
    stats = SpcStats()
    prev = dict(store.get_source(source_id) or {})
    failures = int(prev.get("consecutive_failures") or 0)
    sr_id = store.start_source_run(getattr(ctx, "run_id", None), source_id)
    if hasattr(ctx, "begin_source"):
        ctx.begin_source()
    t0 = time.monotonic()
    created: list[str] = []
    alert: tuple[str, str] | None = None
    error: str | None = None
    try:
        module = importlib.import_module(f"collectors.spc.{MODULES[source_id]}")
        _watch_source(ctx, db, module, source_id, ingredients, stats, created, deadline, clock)
        if stats.failed(len(ingredients)):
            failures += 1
            health = "degraded" if failures >= DEGRADED_AFTER else (prev.get("health") or "unknown")
            store.set_source_state(source_id, health=health, consecutive_failures=failures)
            if health == "degraded" and prev.get("health") != "degraded":
                alert = ("degraded", f"{failures} label-watch runs in a row read no label: "
                                     f"{stats.error_text() or 'no product found'}")
        else:
            store.set_source_state(source_id, health="ok", consecutive_failures=0, ok=True)
        error = stats.error_text()
        if stats.failed(len(ingredients)):
            # a failure, not a note: source_run_failed() (migration 0018) tells the two apart this way
            error = f"no label read: {error or 'no product found'}"[:1000]
    except SourceBlocked as exc:
        error = redact(f"blocked: {exc}")
        store.set_source_state(source_id, health="blocked", consecutive_failures=failures + 1)
        if prev.get("health") != "blocked":
            alert = ("blocked", redact(exc))
    except Exception as exc:  # noqa: BLE001 - the module itself failed: a failed run of the source
        failures += 1
        error = redact(f"{type(exc).__name__}: {exc}")[:1000]
        log.warning("SPC %s failed: %s", source_id, error)
        health = "degraded" if failures >= DEGRADED_AFTER else (prev.get("health") or "unknown")
        store.set_source_state(source_id, health=health, consecutive_failures=failures)
        if health == "degraded" and prev.get("health") != "degraded":
            alert = ("degraded", error)
    finally:
        store.finish_source_run(
            sr_id, http_status=getattr(ctx, "first_status", None), items_seen=stats.products,
            items_new=stats.snapshots, items_matched=stats.issues,
            error=error,
            duration_ms=int((time.monotonic() - t0) * 1000))
    if alert is not None and notifier is not None:
        try:
            notifier.health_alert(source_id, *alert)
        except Exception:  # noqa: BLE001 - an alert failure never fails the run
            log.warning("SPC %s health alert failed", source_id, exc_info=True)
    return created


def run_spc(ctx, db, ingredient_ids: list[str] | None = None, *, store=None,
            notifier=None, deadline: float | None = None,
            clock: Callable[[], float] = time.monotonic, source_ids: list[str] | None = None) -> list[str]:
    """``deadline``: the runner's (a ``clock()`` value); each source gets an even share of what is left.
    ``source_ids``: only these sources (still only when switched on), as the weekly job of one source asks."""
    if store is None:
        from collectors.core.store import Store

        store = Store(db)
    created: list[str] = []
    ingredients = _ingredients(db, ingredient_ids)
    sources = _sources(db)
    if source_ids is not None:
        sources = [s for s in sources if s in source_ids]
    for n, source_id in enumerate(sources):
        share = None
        if deadline is not None:
            now = clock()
            share = now + max(0.0, deadline - now) / (len(sources) - n)
        created += run_source(ctx, db, store, notifier, source_id, ingredients, share, clock)
    return created
