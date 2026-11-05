"""PHAROS collector run.

    python -m collectors.run --schedule 4h|12h|daily|weekly|monthly|all [--source ID]
                             [--backfill] [--probe-id UUID] [--spc-ingredient UUID]
                             [--dry-run] [--no-db]

Per source: a source_run row (the screening log, written even when nothing matched) → list_items →
new items by (source_id, external_id) → fetch_detail → archive → document + attachment rows (PDF
text via collectors.pdf) → matching against the active watchlist → document_text kept only for
matched documents → merge into issues → alerts. Source health follows: ParseError → degraded,
SourceBlocked → blocked, network/HTTP errors → failure count (3 in a row → down), quiet longer than
expected_max_gap_days → degraded.

``--no-db`` runs against an in-memory store (a quick look at a parser; nothing is written anywhere
except the local ./.archive).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from collectors import backfill as bf
from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import (FetchContext, FetchError, ParseError, SourceBlocked,
                                     install_log_redaction, redact)
from collectors.core.imap_inbox import NOT_CONFIGURED
from collectors.core.models import Item, SourceConfig
from collectors.core.registry import load_parser, source_configs, sync_catalogue
from collectors.matching import DocumentMatch, Hit, Matcher
from collectors.merge import DocFacts, merge_document
from collectors.parsers.base import html_text

log = logging.getLogger("collectors.run")

SCHEDULES = ("4h", "12h", "daily", "weekly", "monthly", "all")
MAX_ATTACHMENTS = 8
MAX_NEW_ITEMS = 400            # per source per normal run; the rest wait for the next run
DOWN_AFTER = 3
ALERT_MAX_AGE_DAYS = 60        # an item published longer ago than this never alerts


@dataclass
class SourceStats:
    seen: int = 0
    new: int = 0
    matched: int = 0
    error: str | None = None
    issues_created: int = 0
    failed: bool = False
    alerts: list[str] = field(default_factory=list)


def _utc_midnight(d: date | None) -> datetime | None:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None


def _filename(url: str) -> str:
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name[:200] or "attachment"


class Runner:
    def __init__(self, store: Any, ctx: FetchContext, notifier: Notifier, settings: dict, *,
                 backfill: bool = False, matcher: Matcher | None = None,
                 parser_loader=load_parser) -> None:
        self.store = store
        self.ctx = ctx
        self.notifier = notifier
        self.settings = settings
        self.backfill = backfill
        self.matcher = matcher if matcher is not None else Matcher(store.load_terms())
        self.class_ingredients = store.class_ingredients()
        self.load_parser = parser_loader
        self.backfill_start = bf.cutoff(settings)
        self.summary = bf.BackfillSummary(self.backfill_start)
        self.imap_note: dict[str, str] = {}
        self.issues_created = 0
        self._countries: dict[str, str | None] = {}

    # ───────────────────────────── matching ─────────────────────────────
    def _match_item(self, module: ModuleType, item: Item, lang: str | None) -> list[Hit]:
        hits = self.matcher.match_structured(item.structured, getattr(module, "STRUCTURED_FIELDS", []))
        hits += self.matcher.match_text(item.title, "title", lang=lang)
        hits += self.matcher.match_text(item.body_text, "body", lang=lang)
        return hits

    # ───────────────────────────── one item ─────────────────────────────
    def _attachments(self, item: Item, lang: str | None) -> list[dict]:
        out = []
        for url in item.attachment_urls[:MAX_ATTACHMENTS]:
            try:
                f = self.ctx.get(url, accept="application/pdf,*/*;q=0.8")
            except (FetchError, httpx.HTTPError) as exc:
                log.warning("attachment %s: %s", url, exc)
                continue
            if f.status != 200:
                continue
            text, method, words = "", "none", 0
            if f.is_pdf:
                from collectors.pdf import extract_text

                text, method, words = extract_text(f.content, lang)
            elif f.is_html:
                text = html_text(f)
                method, words = ("html" if text else "none"), len(text.split())
            out.append({"url": url, "filename": _filename(f.final_url), "sha256": f.sha256,
                        "r2_key": f.r2_key, "mime": "application/pdf" if f.is_pdf else f.mime,
                        "bytes": len(f.content), "extraction": method, "words": words,
                        "text": text})
        return out

    def process_item(self, src: SourceConfig, module: ModuleType, item: Item, *,
                     seed: bool, stats: SourceStats) -> None:
        lang = item.lang or src.lang
        detail = src.options.get("detail", "always")
        if hasattr(module, "fetch_detail") and detail != "never":
            if detail != "matched_only" or self._match_item(module, item, lang):
                item = module.fetch_detail(self.ctx, src, item)
                lang = item.lang or src.lang
        attachments = self._attachments(item, lang)
        hits = self._match_item(module, item, lang)
        for k, att in enumerate(attachments):
            hits += self.matcher.match_text(att["text"], "attachment", lang=lang,
                                            ocr=att["extraction"] == "ocr", attachment_index=k)
        dm = DocumentMatch(hits)

        record = self.ctx.archived_for(item.url)
        if record is None:  # a row of a JSON file: the row itself is the original
            raw = json.dumps({"source": src.id, "item": item.structured or {
                "title": item.title, "url": item.url}}, ensure_ascii=False, sort_keys=True,
                default=str).encode("utf-8")
            sha, key = self.ctx.archive(raw, "application/json")
            record = (sha, key, "application/json", len(raw))
        sha, key, mime, size = record
        max_age = int(self.settings.get("alert_max_age_days", ALERT_MAX_AGE_DAYS))
        fresh = item.published is None or (date.today() - item.published).days <= max_age
        # An old notice found by a regular run (a page that lists its whole archive) is history too:
        # it never alerts and never reaches the class-wide digest.
        is_backfill = self.backfill or seed or not fresh
        doc_row = {"source_id": src.id, "external_id": item.external_id, "url": item.url,
                   "title_orig": item.title, "lang": lang, "doc_type": item.doc_type,
                   "published_date": item.published, "sha256": sha, "r2_key": key, "mime": mime,
                   "bytes": size, "extraction": "html" if item.body_text else "none",
                   "structured": item.structured, "is_backfill": is_backfill}

        with self.store.transaction():
            doc_id = self.store.insert_document(doc_row)
            if doc_id is None:
                return  # another run stored it meanwhile
            stats.new += 1
            att_ids = [self.store.insert_attachment({**{k: v for k, v in a.items() if k != "text"},
                                                     "document_id": doc_id}) for a in attachments]
            if not dm:
                return
            stats.matched += 1
            if item.body_text:
                self.store.insert_document_text(doc_id, None, item.body_text)
            for att, att_id in zip(attachments, att_ids, strict=True):
                if att["text"]:
                    self.store.insert_document_text(doc_id, att_id, att["text"])
            for h in hits:
                self.store.insert_match({
                    "document_id": doc_id,
                    "attachment_id": att_ids[h.attachment_index] if h.attachment_index is not None else None,
                    "ingredient_id": h.term.ingredient_id,
                    "class_id": h.term.class_id if not h.term.ingredient_id else None,
                    "term_id": h.term.id if h.term.ingredient_id else None,
                    "class_term_id": h.term.id if not h.term.ingredient_id else None,
                    "field": h.field, "start_offset": h.start, "end_offset": h.end,
                    "matched_text": h.matched_text, "snippet": h.snippet,
                    "confidence": h.confidence})
            ingredients = set(dm.ingredient_ids)
            if dm.class_only:
                for cls in dm.class_ids:
                    ingredients.update(self.class_ingredients.get(cls, []))
            facts = DocFacts(
                document_id=doc_id, source_id=src.id,
                country_code=self._country(src.regulator_id), doc_type=item.doc_type,
                published=item.published, title=item.title,
                text="\n".join(x for x in [item.title, item.body_text or ""]
                               + [a["text"] for a in attachments] if x),
                url=item.url, structured=item.structured, ingredient_ids=ingredients,
                brands=dm.brands, class_only=dm.class_only, is_backfill=is_backfill)
            result = merge_document(self.store, facts)
        if result.created:
            stats.issues_created += 1
            self.issues_created += 1
            if not is_backfill and not dm.class_only and dm.has_high:
                stats.alerts.append(result.issue_id)

    def _country(self, regulator_id: str) -> str | None:
        if regulator_id not in self._countries:
            self._countries[regulator_id] = self.store.country_code(regulator_id)
        return self._countries[regulator_id]

    # ───────────────────────────── one source ─────────────────────────────
    def run_source(self, src: SourceConfig) -> SourceStats:
        stats = SourceStats()
        # a copy: set_source_state below must not change what "the previous health" was
        prev = dict(self.store.get_source(src.id) or {})
        sr_id = self.store.start_source_run(self.ctx.run_id, src.id)
        self.ctx.begin_source()
        t0 = time.monotonic()
        failures = int(prev.get("consecutive_failures") or 0)
        try:
            module = self.load_parser(src.parser)
            items = module.list_items(self.ctx, src)
            stats.seen = len(items)
            known = self.store.known_external_ids(src.id)
            seed = not known and not self.backfill
            fresh: list[Item] = []
            ids: set[str] = set()
            for it in items:
                if it.external_id in known or it.external_id in ids:
                    continue
                if self.backfill and not bf.in_window(it, src, self.backfill_start):
                    continue
                ids.add(it.external_id)
                fresh.append(it)
            if not self.backfill:
                fresh = fresh[:MAX_NEW_ITEMS]
            item_errors: list[str] = []
            for it in fresh:
                try:
                    self.process_item(src, module, it, seed=seed, stats=stats)
                except SourceBlocked:
                    raise
                except (FetchError, httpx.HTTPError, ParseError) as exc:
                    item_errors.append(redact(f"{it.external_id}: {exc}"))
                    log.warning("%s item %s: %s", src.id, it.external_id, redact(exc))
            if fresh and len(item_errors) == len(fresh):
                raise FetchError(0, src.url, f"every new item failed; first: {item_errors[0]}")
            notes = [self.imap_note[src.id]] if src.id in self.imap_note else []
            if item_errors:
                notes.append(f"{len(item_errors)} item(s) failed; first: {item_errors[0]}"[:500])
            stats.error = "; ".join(notes) or None
            latest = max((it.published for it in items if it.published), default=None)
            health = self._quiet_health(src, prev, latest)
            self.store.set_source_state(src.id, health=health, consecutive_failures=0, ok=True,
                                        last_item_at=_utc_midnight(latest))
            if health == "degraded" and prev.get("health") != "degraded":
                self.notifier.health_alert(src.id, "degraded",
                                           f"No new notice for more than {src.expected_max_gap_days} days.")
        except SourceBlocked as exc:
            stats.error = redact(f"blocked: {exc}")
            self.store.set_source_state(src.id, health="blocked", consecutive_failures=failures + 1)
            if prev.get("health") != "blocked":
                self.notifier.health_alert(src.id, "blocked", redact(exc))
        except ParseError as exc:
            stats.failed = True
            stats.error = redact(f"parse: {exc}")
            self.store.set_source_state(src.id, health="degraded", consecutive_failures=failures + 1)
            if prev.get("health") != "degraded":
                self.notifier.health_alert(src.id, "degraded", redact(f"The page changed shape: {exc}"))
        except Exception as exc:  # noqa: BLE001 - network, HTTP, a parser bug: all count as a failure
            failures += 1
            stats.failed = True
            stats.error = redact(f"{type(exc).__name__}: {exc}")[:1000]
            log.warning("%s failed: %s", src.id, redact(traceback.format_exc()))
            health = "down" if failures >= DOWN_AFTER else (prev.get("health") or "unknown")
            if health == "blocked":
                health = "down" if failures >= DOWN_AFTER else "blocked"
            self.store.set_source_state(src.id, health=health, consecutive_failures=failures)
            if failures == DOWN_AFTER:
                self.notifier.health_alert(src.id, "down", stats.error)
        finally:
            self.store.finish_source_run(
                sr_id, http_status=self.ctx.first_status, items_seen=stats.seen,
                items_new=stats.new, items_matched=stats.matched, error=stats.error,
                duration_ms=int((time.monotonic() - t0) * 1000))
        for issue_id in stats.alerts:
            try:
                self.notifier.issue_alert(issue_id)
            except Exception:  # noqa: BLE001 - an alert failure never fails the run
                log.warning("alert for %s failed: %s", issue_id, traceback.format_exc())
        self.summary.add(src.id, seen=stats.seen, new=stats.new, matched=stats.matched,
                         error=stats.error if stats.error and not stats.error.startswith(NOT_CONFIGURED)
                         else None)
        return stats

    @staticmethod
    def _quiet_health(src: SourceConfig, prev: dict, latest: date | None) -> str:
        gap = src.expected_max_gap_days
        last = prev.get("last_item_at")
        candidates = [d for d in (_utc_midnight(latest), last) if d is not None]
        if not gap or not candidates:
            return "ok"
        newest = max(candidates)
        return "degraded" if datetime.now(timezone.utc) - newest > timedelta(days=gap) else "ok"

    # ───────────────────────────── mail ─────────────────────────────
    def pull_mail(self, sources: list[SourceConfig]) -> None:
        allow = {s.id: list(s.options.get("from_domains") or []) for s in sources
                 if s.parser == "email_inbox" and s.options.get("from_domains")}
        if not allow:
            return
        from collectors.core import imap_inbox

        try:
            counts = imap_inbox.collect(self.ctx, allow)
            log.info("imap: %s", counts)
        except RuntimeError as exc:
            if str(exc) == NOT_CONFIGURED:
                for sid in allow:
                    self.imap_note[sid] = NOT_CONFIGURED
            else:
                for sid in allow:
                    self.imap_note[sid] = f"imap: {exc}"[:300]
        except Exception as exc:  # noqa: BLE001 - mail trouble never stops the web sources
            for sid in allow:
                self.imap_note[sid] = f"imap: {type(exc).__name__}: {exc}"[:300]

    def run(self, sources: list[SourceConfig]) -> bool:
        """True when no source failed (a blocked source is a known state, not a failed run)."""
        self.pull_mail(sources)
        results = [self.run_source(src) for src in sources]
        return not any(s.failed for s in results)


def select_sources(sources: list[SourceConfig], schedule: str, source_id: str | None,
                   backfill: bool) -> list[SourceConfig]:
    if source_id:
        chosen = [s for s in sources if s.id == source_id]
        if not chosen:
            raise SystemExit(f"unknown source {source_id}")
        return chosen
    chosen = [s for s in sources if s.enabled and s.kind != "spc"]
    if backfill or schedule == "all":
        return chosen
    return [s for s in chosen if s.schedule == schedule]


def _trigger(args) -> str:
    if args.backfill is not None:
        return "backfill"
    if args.probe_id:
        return "probe"
    return "cron" if os.environ.get("GITHUB_EVENT_NAME") == "schedule" else "manual"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m collectors.run", description=__doc__.split("\n\n")[0])
    p.add_argument("--schedule", choices=SCHEDULES, default="4h")
    p.add_argument("--source", help="run one source by id (whatever its schedule)")
    p.add_argument("--backfill", nargs="?", type=int, const=0, default=None, metavar="MONTHS",
                   help="read history: MONTHS back (default app_setting backfill_months)")
    p.add_argument("--probe-id", help="probe_result id to fill (no documents are written)")
    p.add_argument("--spc-ingredient", help="run the SPC watch for one confirmed ingredient")
    p.add_argument("--dry-run", action="store_true", help="never send a real Telegram message")
    p.add_argument("--no-db", action="store_true", help="in-memory store (local parser check)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backfill_months = args.backfill
    args.backfill = backfill_months is not None
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install_log_redaction()     # no bot token or api_key from httpx's request log, ever
    if args.no_db:
        from collectors.core.memstore import MemoryStore

        db, store = None, MemoryStore()
        store.load_seed()  # the production starting watchlist (lornoxicam + NSAID)
    else:
        from collectors.core.db import Db
        from collectors.core.store import Store

        db = Db()
        store = Store(db)
    settings = store.settings()
    if backfill_months:
        settings["backfill_months"] = backfill_months

    if args.probe_id:
        from collectors.probe import run_probe

        with FetchContext(db, "probe", archive=Archive(enabled=False), dry_run=True) as ctx:
            result = run_probe(store, ctx, args.probe_id)
        print(json.dumps({k: v for k, v in result.items() if k != "items"}, default=str))
        return 0 if result.get("status") == "ok" else 1

    sync_catalogue(store)
    run_id = store.create_run(_trigger(args),
                              os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA"))
    archive = Archive()
    ok = False
    with FetchContext(db, run_id, backfill=args.backfill, archive=archive,
                      dry_run=args.dry_run) as ctx:
        try:
            ctx.watchlist = [r["inn_en"] for r in store.active_ingredients()]
            ctx.backfill_months = int(settings.get("backfill_months", 12) or 12)
            notifier = Notifier(store, settings, dry_run=args.dry_run, archive=archive)
            runner = Runner(store, ctx, notifier, settings, backfill=args.backfill)
            ok = True
            if not args.spc_ingredient:
                sources = select_sources(source_configs(store), args.schedule, args.source,
                                         args.backfill)
                log.info("run %s: %d source(s)", run_id, len(sources))
                ok = runner.run(sources)
            spc_ids: list[str] | None = None
            run_spc_now = False
            if args.spc_ingredient:
                spc_ids, run_spc_now = [args.spc_ingredient], True
            elif not args.source and not args.backfill:
                if args.schedule in ("weekly", "all"):
                    run_spc_now = True          # every active ingredient
                elif args.schedule == "daily":
                    # A newly confirmed ingredient gets its label watch within a day.
                    spc_ids = store.ingredients_without_spc()
                    run_spc_now = bool(spc_ids)
            if db is not None and run_spc_now:
                try:
                    from collectors.spc.run import run_spc

                    created = run_spc(ctx, db, spc_ids, store=store, notifier=notifier)
                    for issue_id in created or []:
                        notifier.issue_alert(issue_id)
                except Exception:  # noqa: BLE001 - SPC trouble is logged, the run continues
                    ok = False
                    log.error("SPC watch failed: %s", traceback.format_exc())
            if args.backfill:
                notifier.admin_message(runner.summary.text(runner.issues_created))
            else:
                notifier.digest_if_due()
        finally:
            store.finish_run(run_id, ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
