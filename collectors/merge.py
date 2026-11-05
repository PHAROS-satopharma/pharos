"""One row per issue: link national copies to their EMA anchor.

Anchors are EMA DHPC, PSUSA and PRAC items. A document is a candidate copy of an anchor when they
share an ingredient (the ATC-anchored ingredient id), the copy is dated between 14 days before and
60 days after the anchor, and the doc types are compatible (recalls never merge with DHPCs).

Score: +3 the anchor's EMA procedure number or EMA page appears in the copy, +2 same brand,
+1 dates within 14 days, +1 same marketing-authorisation holder.
  score ≥ 4 and the copy is from an EU/EEA regulator → linked automatically (method 'auto');
  score 2–3, or any score ≥ 2 outside the EU/EEA → the copy keeps its own issue and is also offered
  to the anchor's issue as method 'suggested' for a reviewer to confirm.
An anchor that arrives after its copies adopts the best-scoring existing issue (≥ 4, EU/EEA) and
becomes its anchor. Class-only documents only ever merge with class-only issues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable

from collectors.matching import norm

ANCHOR_SOURCES = {"ema-dhpc", "ema-psusa", "ema-prac"}
EU_EEA = {"EU", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
          "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI",
          "NO"}

COMPATIBLE: dict[str, set[str]] = {
    "dhpc": {"dhpc", "safety_alert", "safety_update", "signal", "newsletter", "other"},
    "psusa": {"psusa", "label_change", "safety_update", "safety_alert", "newsletter", "other"},
    "signal": {"signal", "dhpc", "safety_alert", "safety_update", "label_change", "newsletter",
               "other"},
}
BEFORE_DAYS = 14   # a copy may precede its anchor by this much
AFTER_DAYS = 60    # … and follow it by this much
CLOSE_DAYS = 14
AUTO_SCORE = 4
SUGGEST_SCORE = 2


@dataclass
class DocFacts:
    document_id: str
    source_id: str
    country_code: str | None
    doc_type: str
    published: date | None
    title: str
    text: str = ""                      # title + body + attachment texts, original language
    url: str = ""
    structured: dict | None = None
    ingredient_ids: set[str] = field(default_factory=set)
    brands: set[str] = field(default_factory=set)    # normalised brand terms that matched
    class_only: bool = False
    is_backfill: bool = False

    @property
    def is_anchor(self) -> bool:
        return self.source_id in ANCHOR_SOURCES

    @property
    def is_eu(self) -> bool:
        return (self.country_code or "").upper() in EU_EEA


@dataclass
class MergeResult:
    issue_id: str
    created: bool
    link: str
    method: str
    score: int | None
    suggested_to: list[str] = field(default_factory=list)
    # An existing issue took this document (a late anchor, or a copy that may bring new ingredients):
    # alert whoever has not had it yet.
    alert: bool = False


def compatible(anchor_type: str, copy_type: str) -> bool:
    if "recall" in (anchor_type, copy_type) or "literature" in (anchor_type, copy_type):
        return anchor_type == copy_type and anchor_type == "recall"
    allowed = COMPATIBLE.get(anchor_type)
    if allowed is None:
        return anchor_type == copy_type
    return copy_type in allowed


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", norm(s))


def procedure_numbers(structured: dict | None) -> list[str]:
    if not structured:
        return []
    out = list(structured.get("procedure_numbers") or [])
    for key in ("procedure_number", "referral_name"):
        v = (structured.get(key) or "").strip()
        if v and "/" in v and v not in out:
            out.append(v)
    return [p for p in out if len(p) >= 8]


def anchor_brands(structured: dict | None) -> set[str]:
    if not structured:
        return set()
    names = []
    for key in ("name_of_medicine", "related_medicines", "brand"):
        names += re.split(r"[;,]", structured.get(key) or "")
    return {norm(n) for n in names if len(n.strip()) >= 3}


def _ema_paths(url: str) -> list[str]:
    m = re.search(r"ema\.europa\.eu(/en/[^\s?#]+)", url or "")
    return [m.group(1).rstrip("/").casefold()] if m else []


def score(anchor: DocFacts, copy: DocFacts, mahs: Iterable[str] = ()) -> tuple[int, list[str]]:
    """Score how likely ``copy`` is a national copy of ``anchor``; returns (score, reasons)."""
    reasons: list[str] = []
    total = 0
    text = copy.text or copy.title
    squashed = _squash(text)
    low = text.casefold()
    if any(_squash(p) in squashed for p in procedure_numbers(anchor.structured)) or any(
            path in low for path in _ema_paths(anchor.url)):
        total += 3
        reasons.append("ema-procedure-or-link")
    ntext = norm(text)
    brands = anchor_brands(anchor.structured) | anchor.brands
    if (copy.brands & brands) or any(re.search(rf"(?<!\w){re.escape(b)}(?!\w)", ntext) for b in brands):
        total += 2
        reasons.append("same-brand")
    if anchor.published and copy.published and abs((copy.published - anchor.published).days) <= CLOSE_DAYS:
        total += 1
        reasons.append("close-date")
    anchor_text = norm(anchor.text or anchor.title)
    for mah in mahs:
        n = norm(mah)
        if len(n) >= 4 and n in ntext and n in anchor_text:
            total += 1
            reasons.append("same-mah")
            break
    return total, reasons


def _facts_from_candidate(doc: dict) -> DocFacts:
    return DocFacts(
        document_id=doc["id"], source_id=doc["source_id"], country_code=doc.get("country_code"),
        doc_type=doc["doc_type"], published=doc.get("published_date"), title=doc.get("title_orig") or "",
        text="\n".join(x for x in (doc.get("title_orig"), doc.get("text")) if x),
        url=doc.get("url") or "", structured=doc.get("structured"))


def _new_issue(store: Any, d: DocFacts, ingredient_ids: Iterable[str]) -> str:
    issue_id = store.create_issue(doc_type=d.doc_type, title=d.title, anchor_document_id=d.document_id,
                                  first_date=d.published, class_only=d.class_only,
                                  is_backfill=d.is_backfill)
    store.link_document(issue_id, d.document_id, link="anchor", method="auto", score=None)
    store.add_issue_ingredients(issue_id, ingredient_ids)
    return issue_id


def merge_document(store: Any, d: DocFacts, ingredient_ids: Iterable[str] | None = None,
                   mahs: Iterable[str] | None = None) -> MergeResult:
    """Place a newly matched document: an existing issue, or a new one (plus suggestions)."""
    ingredients = set(ingredient_ids if ingredient_ids is not None else d.ingredient_ids)
    if d.doc_type == "literature":
        # A paper merges with nothing (compatible()): its own issue, without reading the ingredient's
        # other issues (thousands of papers a year from PubMed Central).
        return MergeResult(_new_issue(store, d, ingredients), True, "anchor", "auto", None)
    mah_list = list(mahs if mahs is not None else store.mah_names(ingredients))
    when = d.published or date.today()
    if d.is_anchor:
        # Copies dated anchor-14 … anchor+60 may already have their own issues.
        candidates = store.candidate_issues(ingredients, when - timedelta(days=BEFORE_DAYS),
                                            when + timedelta(days=AFTER_DAYS)) if ingredients else []
        scored = []
        for iss in candidates:
            docs = iss["documents"]
            if not docs or any(x["source_id"] in ANCHOR_SOURCES for x in docs):
                continue  # another EMA procedure owns that issue
            if iss["class_only"] != d.class_only or not compatible(d.doc_type, iss["doc_type"]):
                continue
            best = max(score(d, _facts_from_candidate(x), mah_list)[0] for x in docs)
            all_eu = all((x.get("country_code") or "").upper() in EU_EEA for x in docs)
            scored.append((best, all_eu, iss))
        scored.sort(key=lambda t: -t[0])
        if scored and scored[0][0] >= AUTO_SCORE and scored[0][1]:
            best, _, iss = scored[0]
            store.link_document(iss["id"], d.document_id, link="anchor", method="auto", score=best)
            store.set_issue_anchor(iss["id"], d.document_id, title=d.title, doc_type=d.doc_type,
                                   first_date=d.published, is_backfill=d.is_backfill)
            store.add_issue_ingredients(iss["id"], ingredients)
            return MergeResult(iss["id"], False, "anchor", "auto", best, alert=True)
        issue_id = _new_issue(store, d, ingredients)
        suggested = []
        for s, _, iss in scored:
            if s >= SUGGEST_SCORE:
                for x in iss["documents"]:
                    store.link_document(issue_id, x["id"], link="copy", method="suggested", score=s)
                suggested.append(iss["id"])
        return MergeResult(issue_id, True, "anchor", "auto", None, suggested)

    # A national (or non-EU) document: look for anchors dated copy-60 … copy+14.
    candidates = store.candidate_issues(ingredients, when - timedelta(days=AFTER_DAYS),
                                        when + timedelta(days=BEFORE_DAYS)) if ingredients else []
    best: tuple[int, dict, bool] | None = None
    for iss in candidates:
        if iss["class_only"] != d.class_only:
            continue
        docs = iss["documents"]
        anchor_doc = next((x for x in docs if x["id"] == iss.get("anchor_document_id")), None)
        if anchor_doc is None and docs:
            anchor_doc = docs[0]
        if anchor_doc is None:
            continue
        a = _facts_from_candidate(anchor_doc)
        if not compatible(a.doc_type, d.doc_type):
            continue
        if not (-BEFORE_DAYS <= ((when - a.published).days if a.published else 0) <= AFTER_DAYS):
            continue
        s, _ = score(a, d, mah_list)
        is_ema = a.source_id in ANCHOR_SOURCES
        if best is None or (s, is_ema) > (best[0], best[2]):
            best = (s, iss, is_ema)
    if best and best[2] and best[0] >= AUTO_SCORE and d.is_eu:
        s, iss, _ = best
        store.link_document(iss["id"], d.document_id, link="copy", method="auto", score=s)
        store.add_issue_ingredients(iss["id"], ingredients)
        if not d.is_backfill:
            store.mark_issue_current(iss["id"])  # a fresh copy of a history issue is news: it alerts
        return MergeResult(iss["id"], False, "copy", "auto", s, alert=True)
    issue_id = _new_issue(store, d, ingredients)
    suggested = []
    if best and best[0] >= SUGGEST_SCORE:
        s, iss, _ = best
        store.link_document(iss["id"], d.document_id, link="copy", method="suggested", score=s)
        suggested.append(iss["id"])
    return MergeResult(issue_id, True, "anchor", "auto", None, suggested)
