"""The check of the past: ``python -m collectors.rematch [--months N | --all] [--trigger daily|manual]``.

The collectors look for the watchlist's words in every notice as it arrives. A word saved later would never
be looked for in what PHAROS already holds: a newly added ingredient (levofloxacin, added on 5 November 2026
after the 12-month backfill, matched nothing at all), a new or changed name, an ingredient watched again
after a pause, or a new class word (``collectors/classes.py``). The database marks each such word as due
(``changed_at`` newer than ``rematched_at``, migration 0034); this job checks the stored notices of the last
12 months (``app_setting.backfill_months``) with the due words only:

* the notice's title, its structured fields and its kept text; when no text was kept (only matched notices
  keep theirs), the archived original is read again from R2: the page (HTML), the PDF (with OCR as on
  arrival) and each attachment that had readable text;
* a word that already matched that notice is skipped, so a notice is never matched twice for one word;
* a notice that now matches gets its match rows and, when it was read again, its text; a notice that
  already belongs to an issue adds the ingredients to that issue; any other is placed exactly as the
  collectors place a new notice (``collectors.merge``), marked as history (``is_backfill``);
* a class-only issue that a due class word had already found gains the ingredients that search the class now
  and that it does not name yet: one linked to the class, or watched again, since (``class_gap``, 0055).
History never sends a Telegram message and never reaches the daily digest.

The progress is kept in ``rematch_job`` (one at a time): the job notes its words and the date it starts
from, walks the notices in id order and saves its place with every notice it changes, so a run that runs out
of time (``PHAROS_TIME_BUDGET_MIN``) is continued by the next one. When it reaches the end the words are
marked as checked as they stood when the job started; a word changed meanwhile stays due for the next job.
Label (SPC) snapshots and literature records are not checked here: literature has its own search.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from collectors import backfill as bf
from collectors.matching import DocumentMatch, Hit, Matcher
from collectors.merge import DocFacts, merge_document
from collectors.parsers.base import html_text

log = logging.getLogger("collectors.rematch")

BATCH = 24                  # notices read and checked together; the time is checked between batches
READERS = 6                 # originals read from R2 at once
MAX_ATTACHMENTS = 8         # as collectors/run.py
ALL_HISTORY = date(2000, 1, 1)


@dataclass
class Texts:
    body: str = ""
    attachments: list[tuple[dict, str]] = field(default_factory=list)   # (attachment row, its text)
    reread: bool = False        # read again from the archive: keep the text if the notice now matches


@dataclass
class Summary:
    job_id: str | None = None
    checked: int = 0
    reread: int = 0
    matched: int = 0
    issues_created: int = 0
    finished: bool = False
    nothing_due: bool = False


# ───────────────────────────── reading the stored notice ─────────────────────────────

def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [value] if isinstance(value, str) else []


def original_text(content: bytes | None, mime: str | None, lang: str | None) -> str:
    """The readable text of an archived original: a PDF (OCR as on arrival), a page, a JSON answer."""
    if not content:
        return ""
    m = (mime or "").split(";")[0].strip().lower()
    if content.lstrip()[:5].startswith(b"%PDF"):
        from collectors.pdf import extract_text

        return extract_text(content, lang)[0]
    if m in ("text/html", "application/xhtml+xml") or content.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        from bs4 import BeautifulSoup

        return html_text(BeautifulSoup(content, "lxml"))
    if m == "application/json" or m.endswith("+json"):
        try:
            data = json.loads(content)
        except ValueError:
            return ""
        if isinstance(data, dict) and set(data) == {"source", "item"}:
            return ""   # a feed or file row PHAROS archived itself: its fields are the structured ones
        return "\n".join(_strings(data))
    if m == "text/plain":
        return content.decode("utf-8", "replace")
    return ""


def kept_texts(doc: dict) -> Texts | None:
    if not doc["texts"]:
        return None
    by_att = {t["attachment_id"]: t["text"] for t in doc["texts"] if t["attachment_id"]}
    return Texts(body="\n".join(t["text"] for t in doc["texts"] if t["attachment_id"] is None),
                 attachments=[(a, by_att.get(a["id"], "")) for a in doc["attachments"]])


def read_again(doc: dict, archive: Any) -> Texts:
    """The texts of a notice that kept none, from its archived original and attachments. An original that
    several notices share (a list page) is not the notice's own text: only its attachments are read."""
    out = Texts(reread=True)
    lang = doc.get("lang")
    try:
        if doc.get("r2_key") and not doc.get("shared_original"):
            out.body = original_text(archive.get(doc["r2_key"]), doc.get("mime"), lang)
    except Exception as exc:
        log.warning("notice %s: its original could not be read again: %s", doc["id"], exc)
    for a in doc["attachments"][:MAX_ATTACHMENTS]:
        text = ""
        if a.get("r2_key") and a.get("extraction") not in (None, "none"):
            try:
                text = original_text(archive.get(a["r2_key"]), a.get("mime"), lang)
            except Exception as exc:
                log.warning("notice %s: attachment %s could not be read again: %s", doc["id"], a.get("url"), exc)
        out.attachments.append((a, text))
    return out


_FIELDS: dict[str, list[str]] = {}


def structured_fields(parser: str | None) -> list[str]:
    """The parser's STRUCTURED_FIELDS, as the collectors match them."""
    if not parser:
        return []
    if parser not in _FIELDS:
        try:
            from collectors.core.registry import load_parser

            _FIELDS[parser] = list(getattr(load_parser(parser), "STRUCTURED_FIELDS", []))
        except Exception:
            _FIELDS[parser] = []
    return _FIELDS[parser]


# ───────────────────────────── one notice ─────────────────────────────

def match_document(matcher: Matcher, doc: dict, texts: Texts,
                   fields: Callable[[str | None], list[str]] = structured_fields) -> list[Hit]:
    lang = doc.get("lang")
    hits = matcher.match_structured(doc.get("structured"), fields(doc.get("parser")))
    hits += matcher.match_text(doc.get("title_orig"), "title", lang=lang)
    hits += matcher.match_text(texts.body, "body", lang=lang)
    for k, (a, text) in enumerate(texts.attachments):
        hits += matcher.match_text(text, "attachment", lang=lang, ocr=a.get("extraction") == "ocr",
                                   attachment_index=k)
    done = doc.get("matched_terms") or set()
    return [h for h in hits if h.term.id not in done]


def class_gap(doc: dict, term_class: dict[str, str], class_ingredients: dict[str, list[str]]) -> set[str]:
    """The ingredients a class-only issue does not name yet although a due class word already matched its
    notice: those that search the class now (linked to it, or watched again, after the notice arrived)."""
    issue = doc.get("issue")
    if not issue or not issue["class_only"]:
        return set()
    classes = {term_class[t] for t in doc.get("matched_terms") or () if t in term_class}
    return {g for c in classes for g in class_ingredients.get(c, [])} - set(issue.get("ingredients") or ())


def record(store: Any, doc: dict, texts: Texts, hits: list[Hit], class_ingredients: dict[str, list[str]]) -> bool:
    """Write what the notice now matches. Returns True when a new (history) issue was made for it."""
    doc_id = doc["id"]
    if texts.reread:
        if texts.body:
            store.insert_document_text(doc_id, None, texts.body)
        for a, text in texts.attachments:
            if text:
                store.insert_document_text(doc_id, a["id"], text)
    for h in hits:
        att = texts.attachments[h.attachment_index][0]["id"] if h.attachment_index is not None else None
        store.insert_match({
            "document_id": doc_id, "attachment_id": att,
            "ingredient_id": h.term.ingredient_id,
            "class_id": h.term.class_id if not h.term.ingredient_id else None,
            "term_id": h.term.id if h.term.ingredient_id else None,
            "class_term_id": h.term.id if not h.term.ingredient_id else None,
            "field": h.field, "start_offset": h.start, "end_offset": h.end,
            "matched_text": h.matched_text, "snippet": h.snippet, "confidence": h.confidence})
    dm = DocumentMatch(hits)
    issue = doc.get("issue")
    if issue:
        if dm.ingredient_ids:
            store.add_issue_ingredients(issue["id"], dm.ingredient_ids)
            if issue["class_only"]:
                store.set_issue_names_ingredient(issue["id"])
        elif issue["class_only"]:
            store.add_issue_ingredients(issue["id"], {g for c in dm.class_ids for g in class_ingredients.get(c, [])})
        return False
    ingredients = set(dm.ingredient_ids)
    if dm.class_only:
        for c in dm.class_ids:
            ingredients.update(class_ingredients.get(c, []))
    title = doc.get("title_orig") or ""
    facts = DocFacts(
        document_id=doc_id, source_id=doc["source_id"], country_code=doc.get("country_code"),
        doc_type=doc["doc_type"], published=doc.get("published_date"), title=title,
        text="\n".join(x for x in [title, texts.body] + [t for _, t in texts.attachments] if x),
        url=doc.get("url") or "", structured=doc.get("structured"), ingredient_ids=ingredients,
        brands=dm.brands, class_only=dm.class_only, is_backfill=True)
    return merge_document(store, facts).created


# ───────────────────────────── the job ─────────────────────────────

def start_job(store: Any, settings: dict, *, months: int | None = None, all_history: bool = False,
              trigger: str = "daily", today: date | None = None) -> dict | None:
    """The open job, or a new one for the words now due; None when nothing is due."""
    job = store.rematch_open_job()
    if job is not None:
        return job
    ing, cls = store.rematch_due_terms()
    if not ing and not cls:
        return None
    if all_history:
        since = ALL_HISTORY
    else:
        since = bf.cutoff({**settings, "backfill_months": months or settings.get("backfill_months", 12)}, today)
    return store.rematch_create_job(since=since, ingredient_term_ids=ing, class_term_ids=cls, trigger=trigger)


def run(store: Any, archive: Any, settings: dict, *, months: int | None = None, all_history: bool = False,
        trigger: str = "daily", deadline: float | None = None, clock: Callable[[], float] = time.monotonic,
        fields: Callable[[str | None], list[str]] = structured_fields, today: date | None = None) -> Summary:
    out = Summary()
    job = start_job(store, settings, months=months, all_history=all_history, trigger=trigger, today=today)
    if job is None:
        out.nothing_due = True
        out.finished = True
        return out
    out.job_id = job["id"]
    terms = store.rematch_terms(job["ingredient_term_ids"], job["class_term_ids"])
    log.info("checking notices since %s for %d words (%d ingredient, %d class)%s", job["since"], len(terms),
             len(job["ingredient_term_ids"]), len(job["class_term_ids"]),
             f", continuing after notice {job['cursor_document_id']}" if job["cursor_document_id"] else "")
    matcher = Matcher(terms)
    class_ingredients = store.class_ingredients()
    term_class = {t.id: t.class_id for t in terms if t.is_class}
    cursor = job["cursor_document_id"]
    while matcher:
        if deadline is not None and clock() >= deadline:
            log.info("out of time: the next run continues after notice %s", cursor)
            return out
        docs = store.rematch_documents(since=job["since"], before=job["started_at"], after_id=cursor, limit=BATCH)
        if not docs:
            break
        need = [d for d in docs if not d["texts"]]
        with ThreadPoolExecutor(max_workers=READERS) as pool:
            read = dict(zip([d["id"] for d in need], pool.map(lambda d: read_again(d, archive), need), strict=True))
        pending = {"checked": 0, "reread": 0}
        for doc in docs:
            texts = kept_texts(doc) or read[doc["id"]]
            hits = match_document(matcher, doc, texts, fields)
            gap = class_gap(doc, term_class, class_ingredients)
            pending["checked"] += 1
            pending["reread"] += int(texts.reread)
            if hits or gap:
                with store.transaction():
                    created = record(store, doc, texts, hits, class_ingredients) if hits else False
                    if gap:
                        store.add_issue_ingredients(doc["issue"]["id"], sorted(gap))
                    store.rematch_advance(job["id"], cursor=doc["id"], matched=1, issues_created=int(created),
                                          **pending)
                out.matched += 1
                out.issues_created += int(created)
                out.checked += pending["checked"]
                out.reread += pending["reread"]
                pending = {"checked": 0, "reread": 0}
            cursor = doc["id"]
        if pending["checked"]:
            store.rematch_advance(job["id"], cursor=cursor, **pending)
            out.checked += pending["checked"]
            out.reread += pending["reread"]
    store.rematch_finish(job["id"])
    out.finished = True
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m collectors.rematch", description=__doc__.split("\n\n")[0])
    p.add_argument("--months", type=int, help="how far back a NEW job checks (default: app_setting.backfill_months)")
    p.add_argument("--all", action="store_true", help="a NEW job checks every stored notice, whatever its date")
    p.add_argument("--trigger", choices=("daily", "manual"), default="daily")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from collectors.core.archive import Archive
    from collectors.core.db import Db
    from collectors.core.store import Store

    budget_min = float(os.environ.get("PHAROS_TIME_BUDGET_MIN") or 0)
    deadline = time.monotonic() + budget_min * 60 if budget_min > 0 else None
    db = Db()
    try:
        store = Store(db)
        out = run(store, Archive(), store.settings(), months=args.months, all_history=args.all,
                  trigger=args.trigger, deadline=deadline)
    finally:
        db.close()
    if out.nothing_due:
        log.info("nothing to check: every watched word has been checked against the stored notices")
    else:
        log.info("checked %d notices (%d read again from the archive): %d now match, %d new history issues; %s",
                 out.checked, out.reread, out.matched, out.issues_created,
                 "finished" if out.finished else "the next run continues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
