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

The first snapshot of a product is a baseline: no change, no issue. Returns the ids of the issues
created, which the runner alerts on.

Module per source: spc-cima → cima, spc-bdpm → bdpm, spc-ema-epar → ema_epar,
spc-dailymed → dailymed, spc-mhra → mhra, spc-pmda → pmda_pi.
"""

from __future__ import annotations

import importlib
import json
import logging
from datetime import date
from typing import Any

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


# ───────────────────────────── archive ─────────────────────────────

def canonical(snapshot: Snapshot) -> bytes:
    """The archived form of a snapshot. Only the texts and their language go in, so a PDF that is
    regenerated with identical text gives the same sha256 (no new snapshot row)."""
    body = {"sections": {k: snapshot.sections[k] for k in sorted(snapshot.sections)},
            "lang": snapshot.lang}
    return json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")


def load_sections(ctx, r2_key: str | None) -> dict[str, str] | None:
    if not r2_key:
        return None
    archiver = getattr(ctx, "archiver", None)
    if archiver is None or not hasattr(archiver, "get"):
        return None
    raw = archiver.get(r2_key)
    if not raw:
        return None
    try:
        return dict(json.loads(raw.decode("utf-8")).get("sections") or {})
    except (ValueError, UnicodeDecodeError, AttributeError):
        return None


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
    db.execute(
        """insert into spc_change (spc_product_id, from_snapshot, to_snapshot, sections, diff,
             issue_id) values (%(p)s, %(f)s, %(t)s, %(s)s, %(d)s, %(i)s)""",
        {"p": product["id"], "f": prev_id, "t": snap_id, "s": sections, "d": _json(changes),
         "i": issue_id})
    return issue_id


def watch_product(db, ctx, module, source_id: str, product: dict, ingredient: dict) -> str | None:
    snap = module.snapshot(ctx, product)
    if snap is None or not snap.sections:
        return None
    snap.sections = {k: v for k, v in snap.sections.items() if normalize(v)}
    raw = canonical(snap)
    sha, key = ctx.archive(raw, "application/json")
    prev = last_snapshot(db, product["id"])
    if prev is not None and prev.get("sha256") == sha:
        return None
    with db.transaction():
        row = db.fetchone(
            """insert into spc_snapshot (spc_product_id, doc_date, sha256, r2_key, section_hashes)
               values (%(p)s, %(d)s, %(s)s, %(k)s, %(h)s) returning id""",
            {"p": product["id"], "d": snap.doc_date, "s": sha, "k": key,
             "h": _json(hashes(snap.sections))})
        snap_id = str(row["id"])
        if prev is None:
            return None                        # baseline
        before = load_sections(ctx, prev.get("r2_key"))
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


def run_spc(ctx, db, ingredient_ids: list[str] | None = None) -> list[str]:
    created: list[str] = []
    ingredients = _ingredients(db, ingredient_ids)
    for source_id in _sources(db):
        module = importlib.import_module(f"collectors.spc.{MODULES[source_id]}")
        for ing in ingredients:
            try:
                found = module.discover(ctx, ing)
            except Exception as exc:  # noqa: BLE001 - one country failing never stops the rest
                log.warning("SPC %s discover %s: %s", source_id, ing["inn_en"], exc)
                continue
            products = []
            with db.transaction():
                for p in found:
                    products.append(upsert_product(db, source_id, ing["id"], p))
                if found:
                    deactivate_missing(db, source_id, ing["id"], [p.national_id for p in found])
            for product in products:
                try:
                    issue = watch_product(db, ctx, module, source_id, product, ing)
                except Exception as exc:  # noqa: BLE001 - logged, next product
                    log.warning("SPC %s %s: %s", source_id, product["national_id"], exc)
                    continue
                if issue:
                    created.append(issue)
    return created
