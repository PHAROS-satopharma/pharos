"""PHAROS — SPC / label watch entry point (``run_spc``), called weekly by ``collectors/run.py``.

For every active ingredient (or the ones given) and every enabled ``kind: spc`` source:

1. **discover** the products authorised in that country (``spc_product``: upsert on
   ``(source_id, national_id)``; products no longer listed are marked inactive);
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

Every SPC source gets a ``source_run`` row per run (products seen, new snapshots, issues, and the
errors: a discovery or a label that failed, labels with no text), and its health: ``ok`` after a run
that read labels, ``blocked`` on a bot check, ``degraded`` after ``DEGRADED_AFTER`` failed runs in a
row (no discovery answered, or not one label could be read) — the admins get the usual health
alert on the change. (SPC sources have no ``expected_max_gap_days``: labels may rightly stay the
same for years, so quiet is not a symptom; failures are.)

Module per source: spc-cima → cima, spc-bdpm → bdpm, spc-ema-epar → ema_epar,
spc-dailymed → dailymed, spc-mhra → mhra, spc-pmda → pmda_pi.
"""

from __future__ import annotations

import importlib
import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import date
from typing import Any

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
}
DEGRADED_AFTER = 2          # failed SPC runs in a row (weekly) before the source is 'degraded'
RECENT_SNAPSHOTS = 10       # how far back a snapshot read the same way is looked for


@dataclass
class SpcStats:
    products: int = 0            # products found (items_seen)
    snapshots: int = 0           # new snapshot rows (items_new)
    issues: int = 0              # label-change issues opened (items_matched)
    labels_read: int = 0
    no_label: int = 0
    discover_ok: int = 0
    errors: list[str] = field(default_factory=list)

    def failed(self, ingredients: int) -> bool:
        """Nothing worked: no discovery answered, or products were found and no label was read."""
        if ingredients and not self.discover_ok:
            return True
        return self.products > 0 and self.labels_read == 0

    def error_text(self) -> str | None:
        notes = []
        if self.errors:
            notes.append(f"{len(self.errors)} error(s); first: {self.errors[0]}")
        if self.no_label:
            notes.append(f"{self.no_label} product(s) without label text")
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
        rows = db.fetchall("select id, inn_en, atc_code from ingredient where id = any(%(ids)s::uuid[])",
                           {"ids": ids})
    else:
        rows = db.fetchall("select id, inn_en, atc_code from ingredient where active order by inn_en")
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
           on conflict (source_id, national_id) do update
             set product_name = excluded.product_name, mah = excluded.mah,
                 url = coalesce(excluded.url, spc_product.url),
                 extra = spc_product.extra || excluded.extra, active = true
           returning id, ingredient_id, source_id, country_code, national_id, product_name, mah,
                     url, extra""",
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


def last_snapshot(db, product_id: str) -> dict | None:
    return db.fetchone(
        """select id, sha256, r2_key, section_hashes from spc_snapshot
            where spc_product_id = %(p)s order by fetched_at desc limit 1""", {"p": product_id})


def recent_snapshots(db, product_id: str, limit: int = RECENT_SNAPSHOTS) -> list[dict]:
    return db.fetchall(
        """select id, sha256, r2_key, section_hashes, doc_date from spc_snapshot
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
         "i": issue_id})
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
    if snap is not None:
        snap.sections = {k: v for k, v in (snap.sections or {}).items() if normalize(v)}
    if snap is None or not snap.sections:
        stats.no_label += 1
        return None
    stats.labels_read += 1
    raw = canonical(snap)
    sha, key = ctx.archive(raw, "application/json")
    rows = recent_snapshots(db, product["id"])
    if rows and rows[0].get("sha256") == sha:
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
            """insert into spc_snapshot (spc_product_id, doc_date, sha256, r2_key, section_hashes)
               values (%(p)s, %(d)s, %(s)s, %(k)s, %(h)s) returning id""",
            {"p": product["id"], "d": snap.doc_date, "s": sha, "k": key,
             "h": _json(hashes(snap.sections))})
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
                  created: list[str]) -> None:
    """Appends to ``created`` as it goes, so issues opened before a bot check are still alerted."""
    for ing in ingredients:
        try:
            found = module.discover(ctx, ing)
        except SourceBlocked:
            raise
        except Exception as exc:  # noqa: BLE001 - one ingredient failing never stops the rest
            stats.errors.append(redact(f"discover {ing['inn_en']}: {type(exc).__name__}: {exc}"))
            log.warning("SPC %s discover %s: %s", source_id, ing["inn_en"], redact(exc))
            continue
        stats.discover_ok += 1
        stats.products += len(found)
        products = []
        with db.transaction():
            for p in found:
                products.append(upsert_product(db, source_id, ing["id"], p))
            if found:
                deactivate_missing(db, source_id, ing["id"], [p.national_id for p in found])
        for product in products:
            try:
                issue = watch_product(db, ctx, module, source_id, product, ing, stats)
            except SourceBlocked:
                raise
            except Exception as exc:  # noqa: BLE001 - recorded, next product
                stats.errors.append(redact(f"{product['national_id']}: {type(exc).__name__}: {exc}"))
                log.warning("SPC %s %s: %s", source_id, product["national_id"], redact(exc))
                continue
            if issue:
                stats.issues += 1
                created.append(issue)


def run_source(ctx, db, store, notifier, source_id: str, ingredients: list[dict]) -> list[str]:
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
        _watch_source(ctx, db, module, source_id, ingredients, stats, created)
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
            notifier=None) -> list[str]:
    if store is None:
        from collectors.core.store import Store

        store = Store(db)
    created: list[str] = []
    ingredients = _ingredients(db, ingredient_ids)
    for source_id in _sources(db):
        created += run_source(ctx, db, store, notifier, source_id, ingredients)
    return created
