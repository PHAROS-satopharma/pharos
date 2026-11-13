"""PHAROS collector run.

    python -m collectors.run --schedule 4h|12h|daily|literature|weekly|monthly|all [--source ID]
                             [--backfill] [--probe-id UUID] [--spc-ingredient UUID] [--spc-source ID]
                             [--dry-run] [--no-db]

Per source: a source_run row (the screening log, written even when nothing matched) → list_items →
new items by (source_id, external_id) → fetch_detail → archive → document + attachment rows (PDF
text via collectors.pdf) → matching against the active watchlist → document_text kept only for
matched documents → merge into issues → alerts. Source health follows: ParseError → degraded,
SourceBlocked → blocked, network/HTTP errors → failure count (3 in a row → down), quiet longer than
expected_max_gap_days → degraded.

``--spc-source`` is one job of the weekly label watch (``label-watch.yml``): that source's labels for every watched
ingredient, with the whole time budget, and nothing else — no other source, no catalogue sync, no label comparison,
digest or reminder (seventeen such jobs run at once; the regular runs keep those).

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
from zoneinfo import ZoneInfo

import httpx

from collectors import backfill as bf
from collectors import reminders
from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import (FetchContext, FetchError, NotSetUp, ParseError, SourceBlocked,
                                     install_log_redaction, redact)
from collectors.core.imap_inbox import NOT_CONFIGURED
from collectors.core.models import Item, SourceConfig
from collectors.core.registry import load_parser, source_configs, sync_catalogue
from collectors.matching import DocumentMatch, Hit, Matcher
from collectors.merge import DocFacts, merge_document
from collectors.parsers import base as parser_base
from collectors.parsers.base import html_text

log = logging.getLogger("collectors.run")

CASE_NAMES_MIN = 8   # minutes for the case report name check after a literature run's searches
SCHEDULES = ("4h", "12h", "daily", "literature", "weekly", "monthly", "all")
MAX_ATTACHMENTS = 8
MAX_NEW_ITEMS = 400            # per source per normal run; the rest wait for the next run
SOURCE_BUDGET_S = 10 * 60      # per source per normal run: one slow source never starves the others
DOWN_AFTER = 3
ALERT_MAX_AGE_DAYS = 60        # an item published longer ago than this never alerts


def run_failed(results: list["SourceStats"]) -> bool:
    """A run fails only when MORE THAN HALF of the sources it read failed (or its only one did).

    One unreachable regulator site (Jordan's timed out twice on 10 Nov) must not turn every collect
    run red: that source keeps its own health, its consecutive-failure count and its "down" alert
    after DOWN_AFTER runs in a row. A run where most sources fail is a systemic fault (network,
    database, a broken release) and still fails, so GitHub still says so.
    """
    failed = sum(1 for s in results if s.failed)
    return failed > 0 and failed * 2 > len(results)


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


def possible_gap(src: SourceConfig, items: list, known: set[str], prev: dict) -> str | None:
    """A list that has moved past everything PHAROS holds: every listed item is new, and the oldest of them
    is newer than the newest stored one. Whatever was published in between dropped off before a run read
    it (the UK alerts' 20-entry feed lost eight Safety Roundups this way, found 6 Nov 2026). Not for a
    mailbox (it lists only unread mail), literature or labels, or a source with ``gap_check: false``."""
    if (src.kind in ("literature", "spc") or src.channel == "email" or src.options.get("gap_check") is False
            or not known or len(items) < 3 or any(it.external_id in known for it in items)):
        return None
    oldest = min((it.published for it in items if it.published), default=None)
    last = prev.get("last_item_at")
    last = last.date() if isinstance(last, datetime) else last
    if oldest is None or last is None or oldest <= last + timedelta(days=1):
        return None
    return (f"Possible gap: all {len(items)} listed notices are new, the oldest from {oldest:%d %b %Y}, and "
            f"the newest one PHAROS held was from {last:%d %b %Y}. Notices published in between may have "
            f"dropped off the list before a run read them; check the regulator's page.")


def latest_published(items: list) -> date | None:
    """The newest publication date among the items, ignoring any dated after tomorrow (UTC): a date in
    the future is a misread, and the source's last-item date only ever moves forward, so one would
    stick (the UK alerts feed once showed 10 Dec 2026 for a recall of 12 Oct 2026)."""
    limit = datetime.now(timezone.utc).date() + timedelta(days=1)
    return max((it.published for it in items if it.published and it.published <= limit), default=None)


def _filename(url: str) -> str:
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name[:200] or "attachment"


class Runner:
    def __init__(self, store: Any, ctx: FetchContext, notifier: Notifier, settings: dict, *,
                 backfill: bool = False, matcher: Matcher | None = None,
                 parser_loader=load_parser, deadline: float | None = None,
                 clock=time.monotonic) -> None:
        self.store = store
        self.ctx = ctx
        ctx.store = store                 # a parser that remembers its searches (NCBI literature) reads it
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
        self.deadline = deadline          # time.monotonic() value: no new item or source after it
        self.clock = clock
        self.skipped: list[str] = []      # sources left for the next run when the time ran out

    def out_of_time(self, source_started: float | None = None, budget_s: float = SOURCE_BUDGET_S) -> bool:
        now = self.clock()
        if self.deadline is not None and now >= self.deadline:
            return True
        return (source_started is not None and not self.backfill
                and now - source_started >= budget_s)

    # ───────────────────────────── matching ─────────────────────────────
    def _match_item(self, module: ModuleType, item: Item, lang: str | None) -> list[Hit]:
        hits = self.matcher.match_structured(item.structured, getattr(module, "STRUCTURED_FIELDS", []))
        hits += self.matcher.match_text(item.title, "title", lang=lang)
        hits += self.matcher.match_text(item.body_text, "body", lang=lang)
        return hits

    # ───────────────────────────── one item ─────────────────────────────
    def _attachments(self, item: Item, lang: str | None, *, columns: bool = False) -> list[dict]:
        """``columns``: the parser's ``PDF_COLUMNS`` — its PDFs are printed in two columns and are read
        column by column (``collectors.pdf.extract_text_by_columns``), not straight across."""
        out = []
        for url in item.attachment_urls[:MAX_ATTACHMENTS]:
            try:
                f = self.ctx.get(url, accept="application/pdf,*/*;q=0.8")
            except (FetchError, httpx.HTTPError) as exc:
                log.warning("attachment %s: %s", url, exc)
                continue
            except SourceBlocked as exc:
                # One linked file behind a bot check (an ANSM notice links a PDF on sante.gouv.fr) is
                # skipped, never bypassed; the source itself was read, so it is not "blocked".
                log.warning("attachment %s: %s", url, exc)
                continue
            if f.status != 200:
                continue
            text, method, words = "", "none", 0
            if f.is_pdf and columns:
                from collectors.pdf import extract_text_by_columns

                text, method, words, by_columns = extract_text_by_columns(f.content, lang)
                if not by_columns:
                    log.warning("attachment %s: read straight across, the word boxes were unavailable", url)
            elif f.is_pdf:
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
        max_age = int(self.settings.get("alert_max_age_days", ALERT_MAX_AGE_DAYS))
        fresh = item.published is None or (date.today() - item.published).days <= max_age
        detail = src.options.get("detail", "always")
        if not fresh and detail == "always" and src.options.get("old_detail") == "matched_only":
            detail = "matched_only"   # an old notice never alerts: open its page only if its row matched
        if hasattr(module, "fetch_detail") and detail != "never":
            if detail != "matched_only" or self._match_item(module, item, lang):
                item = module.fetch_detail(self.ctx, src, item)
                lang = item.lang or src.lang
        attachments = self._attachments(item, lang, columns=getattr(module, "PDF_COLUMNS", False))
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
        # An old notice found by a regular run (a page that lists its whole archive) is history too:
        # it never alerts and never reaches the class-wide digest.
        # A paper found by a search's first look-back (NCBI literature) is history too.
        is_backfill = (self.backfill or seed or not fresh
                       or bool(hasattr(module, "is_history") and module.is_history(item)))
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
        # papers are read on the Ingredients screen and in the weekly report, never on Telegram
        paper = src.kind == "literature" or item.doc_type == "literature"
        if (result.created or result.alert) and not is_backfill and not dm.class_only and dm.has_high \
                and not paper:
            stats.alerts.append(result.issue_id)

    def _country(self, regulator_id: str) -> str | None:
        if regulator_id not in self._countries:
            self._countries[regulator_id] = self.store.country_code(regulator_id)
        return self._countries[regulator_id]

    # ───────────────────────────── one source ─────────────────────────────
    def _watched(self, text: str) -> bool:
        return any(h.term.ingredient_id for h in self.matcher.match_text(text, "title"))

    def run_source(self, src: SourceConfig) -> SourceStats:
        stats = SourceStats()
        # A keyword filter never drops a notice that names a watched ingredient (parsers/base.py); the
        # filters' state is this source's only: set here, emptied when the source is done.
        parser_base.WATCHED = self._watched
        # a copy: set_source_state below must not change what "the previous health" was
        prev = dict(self.store.get_source(src.id) or {})
        try:
            sr_id = self.store.start_source_run(self.ctx.run_id, src.id)
        except Exception:
            # Removed on Sources since this run listed it (0100: only a source never read is deleted): the
            # rest of the run goes on without it.
            if self.store.get_source(src.id) is None:
                log.warning("source %s was removed during the run; skipped", src.id)
                parser_base.WATCHED = None
                return stats
            raise
        self.ctx.begin_source()
        self.ctx.last_ok_at = prev.get("last_ok_at")
        t0 = time.monotonic()
        started = self.clock()
        failures = int(prev.get("consecutive_failures") or 0)
        try:
            module = self.load_parser(src.parser)
            self.ctx.held_back = 0      # new items a parser found but did not read, over max_new_items
            self.ctx.list_errors = []   # parts of the list a parser could not read (an MHRA roundup)
            parser_base.DROPPED.clear()
            items = module.list_items(self.ctx, src)
            stats.seen = len(items)
            if parser_base.DROPPED:     # what the source's filters left out, kept to be checked (0074)
                self.store.record_filtered(src.id, list(parser_base.DROPPED))
            known = self.store.known_external_ids(src.id)
            gap = None if self.backfill else possible_gap(src, items, known, prev)
            if gap:
                log.warning("%s: %s", src.id, gap)
                self.notifier.health_alert(src.id, "gap", gap)
            # The first normal run of a source is its seed (never alerts) until one run has completed:
            # a first run cut short by the time budget keeps seeding on the next run.
            seed = not self.backfill and (not known or prev.get("last_ok_at") is None)
            fresh: list[Item] = []
            ids: set[str] = set()
            aliases = getattr(module, "aliases", lambda _: [])   # a paper stored under its PMC id
            for it in items:
                if it.external_id in known or it.external_id in ids:
                    continue
                if any(a in known or a in ids for a in aliases(it)):
                    continue
                if self.backfill and not bf.in_window(it, src, self.backfill_start):
                    continue
                ids.add(it.external_id)
                fresh.append(it)
            held = 0
            if not self.backfill:
                cap = int(src.options.get("max_new_items", MAX_NEW_ITEMS))
                held = max(0, len(fresh) - cap) + int(getattr(self.ctx, "held_back", 0) or 0)
                fresh = fresh[:cap]
            item_errors: list[str] = []
            waiting = 0
            stored = set(known)  # every item now in the database: known before, or stored by this run
            budget_s = float(src.options.get("time_budget_min", SOURCE_BUDGET_S / 60)) * 60
            for k, it in enumerate(fresh):
                if self.out_of_time(started, budget_s):
                    waiting = len(fresh) - k
                    break
                try:
                    self.process_item(src, module, it, seed=seed, stats=stats)
                    stored.add(it.external_id)
                except SourceBlocked:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad notice never stops the ones behind it
                    item_errors.append(redact(f"{it.external_id}: {type(exc).__name__}: {exc}"))
                    log.warning("%s item %s: %s", src.id, it.external_id, redact(traceback.format_exc()))
            if hasattr(module, "after_store"):
                # a parser that consumes its input (the mailbox) marks only what is now stored
                module.after_store(self.ctx, src, items, stored)
            tried = len(fresh) - waiting
            if tried and len(item_errors) == tried:
                raise FetchError(0, src.url, f"every new item failed; first: {item_errors[0]}")
            # Notes on a completed run; source_run_failed() (migration 0018) knows each of their
            # beginnings, so a new kind of note is added there too.
            notes = [self.imap_note[src.id]] if src.id in self.imap_note else []
            # a part of the list not read is a note like a bad notice: the rest is stored, the part tried again
            missed = [redact(e) for e in getattr(self.ctx, "list_errors", None) or []] + item_errors
            if missed:
                notes.append(f"{len(missed)} item(s) failed; first: {missed[0]}"[:500])
            if waiting:
                notes.append(f"time budget reached: {waiting} new item(s) wait for the next run")
                log.warning("%s: time budget reached, %d new item(s) wait", src.id, waiting)
            if held:
                notes.append(f"item cap reached: {held} new item(s) wait for the next run")
                log.warning("%s: item cap reached, %d new item(s) wait", src.id, held)
            stats.error = "; ".join(notes) or None
            latest = latest_published(items)
            health = self._quiet_health(src, prev, latest)
            # ok=True records a COMPLETE run; a run cut short by the time budget or the item cap leaves
            # last_ok_at alone (a seed continues; NCBI's next window still covers the papers held back)
            self.store.set_source_state(src.id, health=health, consecutive_failures=0,
                                        ok=not waiting and not held, last_item_at=_utc_midnight(latest))
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
                what = "Not set up yet" if isinstance(exc, NotSetUp) else "The page changed shape"
                self.notifier.health_alert(src.id, "degraded", redact(f"{what}: {exc}"))
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
            parser_base.WATCHED = None
            parser_base.DROPPED.clear()
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
        if not candidates and src.channel == "email" and prev.get("created_at"):
            # A mail source that never received a notice waits from the day it was added; past its gap,
            # the subscription is checked (the Sources screen says "Waiting for the first e-mail" until then).
            candidates = [prev["created_at"]]
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

        held: dict[str, int] = {}
        try:
            counts = imap_inbox.collect(self.ctx, allow, held=held)
            log.info("imap: %s", counts)
            for sid, n in held.items():
                self.imap_note[sid] = (f"imap: {n} message(s) held unread: sender not verified "
                                       "(no DMARC, DKIM or SPF pass) or too big")
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
        """True unless more than half of the sources failed (see run_failed; a blocked source is a
        known state, not a failure)."""
        self.pull_mail(sources)
        # The least recently completed source goes first, so one cut-short run never starves the
        # same sources twice.
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        order = sorted(sources, key=lambda s: (self.store.get_source(s.id) or {}).get("last_ok_at")
                       or epoch)
        results: list[SourceStats] = []
        down: list[str] = []
        for src in order:
            if self.out_of_time():
                self.skipped.append(src.id)
                continue
            stats = self.run_source(src)
            results.append(stats)
            if stats.failed:
                down.append(src.id)
        if self.skipped:
            log.warning("time budget reached: %d source(s) wait for the next run: %s",
                        len(self.skipped), ", ".join(self.skipped))
        if down and not run_failed(results):
            log.warning("%d of %d source(s) failed and wait for the next run; the run is not failed "
                        "by them: %s", len(down), len(results), ", ".join(down))
        return not run_failed(results)


def select_sources(sources: list[SourceConfig], schedule: str, source_id: str | None,
                   backfill: bool) -> list[SourceConfig]:
    if source_id:
        chosen = [s for s in sources if s.id == source_id]
        if not chosen:
            raise SystemExit(f"unknown source {source_id}")
        return chosen
    chosen = [s for s in sources if s.enabled and s.kind != "spc"]
    if backfill:
        # The mailbox holds only new mail (its unread messages and the rows of the last 14 days): a backfill would
        # file it as history and it would never alert. Mail stays with the regular run, which also keeps one
        # reader on the mailbox now that a backfill runs beside a collection (backfill.yml).
        return [s for s in chosen if s.channel != "email"]
    if schedule == "all":
        return chosen
    if schedule == "literature":
        # the daily run's literature sources (NCBI) twice more a day, so a new ingredient's look-back is not
        # left for the night; a source switched off on the Sources screen stays off
        return [s for s in chosen if s.kind == "literature"]
    return [s for s in chosen if s.schedule == schedule]


def _trigger(args) -> str:
    if args.backfill is not None:
        return "backfill"
    if args.probe_id:
        return "probe"
    # repository_dispatch "collect" is the database's back-up timer for a slot GitHub skipped.
    event = os.environ.get("GITHUB_EVENT_NAME")
    return "cron" if event in ("schedule", "repository_dispatch") else "manual"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m collectors.run", description=__doc__.split("\n\n")[0])
    p.add_argument("--schedule", choices=SCHEDULES, default="4h")
    p.add_argument("--source", help="run one source by id (whatever its schedule)")
    p.add_argument("--backfill", nargs="?", type=int, const=0, default=None, metavar="MONTHS",
                   help="read history: MONTHS back (default app_setting backfill_months)")
    p.add_argument("--probe-id", help="probe_result id to fill (no documents are written)")
    p.add_argument("--spc-ingredient", help="run the SPC watch for one confirmed ingredient")
    p.add_argument("--spc-source", help="run the SPC watch of one label source for every ingredient (weekly job)")
    p.add_argument("--dry-run", action="store_true", help="never send a real Telegram message")
    p.add_argument("--no-db", action="store_true", help="in-memory store (local parser check)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    trigger = _trigger(args)    # before args.backfill turns into True/False below (False "is not None" too)
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

        # public_only: an admin-typed link (and every redirect from it) never reaches a private network
        with FetchContext(db, "probe", archive=Archive(enabled=False), dry_run=True,
                          public_only=True) as ctx:
            result = run_probe(store, ctx, args.probe_id)
        print(json.dumps({k: v for k, v in result.items() if k != "items"}, default=str))
        # A site that refuses, or a page with no reading rules, is the probe's answer and is already on
        # the admin screen: the job stays green. Only a probe that could not be read or written fails it.
        return 0

    if args.spc_source:
        from collectors.spc.run import MODULES

        if args.spc_source not in MODULES:
            raise SystemExit(f"unknown label source {args.spc_source}")
    else:
        sync_catalogue(store)
    # a job of the weekly label watch serves the weekly slot: the database's back-up timer sees it started (0112)
    slot = None if (args.backfill or args.source or args.spc_ingredient) else args.schedule
    run_id = store.create_run(trigger,
                              os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA"), slot)
    archive = Archive()
    t_start = time.monotonic()
    ok = False
    completed = False  # a run that raised is never recorded as successful
    # public_only: a saved user-added source is read on every run; it never reaches a private network
    with FetchContext(db, run_id, backfill=args.backfill, archive=archive,
                      dry_run=args.dry_run, public_only=True) as ctx:
        try:
            ctx.watchlist = [r["inn_en"] for r in store.active_ingredients()]
            ctx.backfill_months = int(settings.get("backfill_months", 12) or 12)
            notifier = Notifier(store, settings, dry_run=args.dry_run, archive=archive)
            budget_min = float(os.environ.get("PHAROS_TIME_BUDGET_MIN") or 0)
            runner = Runner(store, ctx, notifier, settings, backfill=args.backfill,
                            deadline=t_start + budget_min * 60 if budget_min > 0 else None)
            ok = True
            if not args.spc_ingredient and not args.spc_source:
                sources = select_sources(source_configs(store), args.schedule, args.source,
                                         args.backfill)
                log.info("run %s: %d source(s)", run_id, len(sources))
                ok = runner.run(sources)
                if db is not None and not args.backfill and any(s.kind == "literature" for s in sources):
                    try:
                        # a possible case report must name its ingredient in its title or abstract
                        from collectors import case_names

                        # its own few minutes after the searches, which use the whole time budget
                        case_names.check(ctx, store, datetime.now(ZoneInfo("Africa/Cairo")).date(),
                                         deadline=time.monotonic() + CASE_NAMES_MIN * 60)
                    except Exception:  # noqa: BLE001 - checked again on the next run
                        log.warning("case report name check failed: %s", traceback.format_exc())
            spc_ids: list[str] | None = None
            spc_sources: list[str] | None = None
            run_spc_now = False
            if args.spc_ingredient:
                spc_ids, run_spc_now = [args.spc_ingredient], True
            elif args.spc_source:
                spc_sources, run_spc_now = [args.spc_source], True     # every active ingredient
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

                    created = run_spc(ctx, db, spc_ids, store=store, notifier=notifier,
                                      deadline=runner.deadline, source_ids=spc_sources)
                except Exception:  # noqa: BLE001 - SPC trouble is logged, the run continues
                    ok, created = False, []
                    log.error("SPC watch failed: %s", traceback.format_exc())
                for issue_id in created or []:
                    try:
                        notifier.issue_alert(issue_id)
                    except Exception:  # noqa: BLE001 - one alert failing never stops the others
                        log.warning("alert for %s failed: %s", issue_id, traceback.format_exc())
            if db is not None and not (args.backfill or args.source or args.probe_id or args.spc_source):
                try:
                    # our label against the label changes of the last year (label_gap, 0043): a new version of
                    # our label uploaded on the screen is compared with them on this run
                    from collectors.labels.recompute import recompute_gaps

                    recompute_gaps(db)
                except Exception:  # noqa: BLE001 - the comparison never fails the run
                    log.warning("label gap check failed: %s", traceback.format_exc())
            if args.backfill:
                notifier.admin_message(runner.summary.text(runner.issues_created))
            elif not args.spc_source:
                try:
                    # an immediate alert Telegram refused on an earlier run is tried again
                    notifier.retry_refused_alerts()
                except Exception:  # noqa: BLE001 - an alert failure never fails the run
                    log.warning("alert retry failed: %s", traceback.format_exc())
                notifier.digest_if_due()
                try:
                    # once a day: how many items each country's authorities published
                    notifier.new_items_digest_if_due()
                except Exception:  # noqa: BLE001 - the daily message never fails the run
                    log.warning("new-items message failed: %s", traceback.format_exc())
                try:
                    # once a day: the findings late or due within two days to the Egyptian Drug Authority
                    reminders.remind_if_due(store, notifier, now=notifier.now)
                except Exception:  # noqa: BLE001 - the reminder never fails the run
                    log.warning("authority reminder failed: %s", traceback.format_exc())
            completed = True
        finally:
            store.finish_run(run_id, ok and completed)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
