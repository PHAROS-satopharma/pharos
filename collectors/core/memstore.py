"""In-memory ``Store`` twin for fixture tests and ``--no-db`` local runs. Same methods, no SQL."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from collectors.core.models import SourceConfig
from collectors.core.store import DEFAULT_SETTINGS
from collectors.matching import Term

SEED_SQL = Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0003_seed_watchlist.sql"
_SEED_CLASS_ROW = re.compile(r"^\s*\('([a-z]{2})',\s*'([^']+)',\s*'(stem|exact|substring)'\)", re.M)
_SEED_TERM_ROW = re.compile(
    r"^\s*\('([a-z]{2})',\s*'([^']+)',\s*'(\w+)',\s*'(stem|exact|substring)',\s*'\{([^}]*)\}'\)", re.M)


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    """Tables are plain lists/dicts so a test can seed and inspect them directly."""

    db = None

    def __init__(self) -> None:
        self.app_setting: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.regulator: dict[str, dict] = {}
        self.source: dict[str, dict] = {}
        self.run: dict[str, dict] = {}
        self.source_run: dict[str, dict] = {}
        self.document: dict[str, dict] = {}
        self.attachment: dict[str, dict] = {}
        self.document_text: list[dict] = []
        self.match: list[dict] = []
        self.ingredient: dict[str, dict] = {}
        self.terms: list[Term] = []
        self.ingredient_class: list[tuple[str, str]] = []  # (ingredient_id, class_id)
        # (ingredient_id, class_id) -> {"relation": group|parent|manual, "enabled"}; a link without an entry
        # is a searched group (the default of migration 0049)
        self.ingredient_class_state: dict[tuple[str, str], dict] = {}
        self.spc_mah: dict[str, list[str]] = {}
        self.issue: dict[str, dict] = {}
        self.issue_document: list[dict] = []
        self.issue_ingredient: list[tuple[str, str]] = []
        self.person: dict[str, dict] = {}
        self.review_event: list[dict] = []      # {id, issue_id, to_status, person_id, created_at}
        self.authority_report: list[dict] = []  # {id, issue_id, decision_id, sent_on, …, withdrawn_at, created_at}
        self.subscription: list[dict] = []
        self.notification: list[dict] = []
        self.probe_result: dict[str, dict] = {}
        self.literature_search: dict[tuple[str, str], dict] = {}
        self.drug_class: dict[str, dict] = {}              # id -> {code, name_en, origin, wikidata_qid}
        # term id -> {"changed_at", "rematched_at"}; a term without an entry was already checked against the past
        self.term_state: dict[str, dict] = {}
        self.rematch_job: dict[str, dict] = {}

    @contextmanager
    def transaction(self):
        yield self

    # ───────────────────────────── seed ─────────────────────────────
    def load_seed(self, path: str | Path = SEED_SQL) -> tuple[str, str]:
        """Load the watchlist seed migration (lornoxicam + NSAID) so ``--no-db`` runs and tests use
        the very terms production starts with. Returns (ingredient_id, class_id)."""
        sql = Path(path).read_text(encoding="utf-8")
        ing_id, cls_id = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
        self.ingredient[ing_id] = {"inn_en": "lornoxicam", "atc_code": "M01AC05", "active": True}
        self.drug_class[cls_id] = {"code": "NSAID", "name_en": "Non-steroidal anti-inflammatory drugs",
                                   "origin": "hand", "wikidata_qid": None}
        self.ingredient_class.append((ing_id, cls_id))
        self.ingredient_class_state[(ing_id, cls_id)] = {"relation": "manual", "enabled": True}
        class_part, _, ing_part = sql.partition("insert into ingredient (")
        n = 0
        for m in _SEED_CLASS_ROW.finditer(class_part):
            n += 1
            self.terms.append(Term(id=f"ct-{n}", term=m.group(2), lang=m.group(1), mode=m.group(3),
                                   class_id=cls_id, kind="class"))
        for m in _SEED_TERM_ROW.finditer(ing_part):
            n += 1
            excl = tuple(x for x in m.group(5).split(",") if x)
            self.terms.append(Term(id=f"t-{n}", term=m.group(2), lang=m.group(1), mode=m.group(4),
                                   exclusions=excl, ingredient_id=ing_id, kind=m.group(3)))
        return ing_id, cls_id

    # ───────────────────────────── settings / catalogue ─────────────────────────────
    def settings(self) -> dict[str, Any]:
        return dict(self.app_setting)

    def upsert_regulator(self, reg: dict) -> None:
        self.regulator[reg["id"]] = dict(reg)

    def upsert_catalogue_source(self, src: SourceConfig, notes: str | None) -> None:
        row = self.source.get(src.id)
        if row and row.get("origin") == "user":
            return
        base = row or {"enabled": src.enabled, "origin": "catalogue", "health": "unknown",
                       "consecutive_failures": 0, "last_ok_at": None, "last_item_at": None}
        base.update(id=src.id, regulator_id=src.regulator_id, kind=src.kind, channel=src.channel,
                    url=src.url, parser=src.parser, languages=list(src.languages),
                    schedule=src.schedule, expected_max_gap_days=src.expected_max_gap_days,
                    notes=notes, page_url=src.page_url)
        self.source[src.id] = base

    def list_sources(self) -> list[dict]:
        return [dict(v) for _, v in sorted(self.source.items())]

    def get_source(self, source_id: str) -> dict | None:
        return self.source.get(source_id)

    def country_code(self, regulator_id: str) -> str | None:
        return (self.regulator.get(regulator_id) or {}).get("country_code")

    # ───────────────────────────── runs ─────────────────────────────
    def create_run(self, trigger: str, git_sha: str | None, schedule: str | None = None) -> str:
        rid = _id()
        self.run[rid] = {"id": rid, "trigger": trigger, "git_sha": git_sha, "schedule": schedule,
                         "started_at": _now(), "finished_at": None, "ok": None}
        return rid

    def finish_run(self, run_id: str, ok: bool) -> None:
        self.run[run_id].update(finished_at=_now(), ok=ok)

    def start_source_run(self, run_id: str, source_id: str) -> str:
        sid = _id()
        self.source_run[sid] = {"id": sid, "run_id": run_id, "source_id": source_id,
                                "started_at": _now(), "items_seen": 0, "items_new": 0,
                                "items_matched": 0, "error": None}
        return sid

    def finish_source_run(self, source_run_id: str, **fields: Any) -> None:
        self.source_run[source_run_id].update(finished_at=_now(), **fields)

    def set_source_state(self, source_id: str, *, health: str, consecutive_failures: int,
                         ok: bool = False, last_item_at: datetime | None = None) -> None:
        row = self.source[source_id]
        row["health"] = health
        row["consecutive_failures"] = consecutive_failures
        if ok:
            row["last_ok_at"] = _now()
        if last_item_at and (row.get("last_item_at") is None or last_item_at > row["last_item_at"]):
            row["last_item_at"] = last_item_at

    # ───────────────────────────── documents ─────────────────────────────
    def known_external_ids(self, source_id: str) -> set[str]:
        return {d["external_id"] for d in self.document.values() if d["source_id"] == source_id}

    def literature_known_ids(self, source_id: str) -> set[str]:
        docs = [d for d in self.document.values() if d["source_id"] == source_id]
        return ({d["external_id"] for d in docs}
                | {(d.get("structured") or {}).get("pmcid") for d in docs if (d.get("structured") or {}).get("pmcid")})

    def literature_searches(self) -> dict[tuple[str, str], dict]:
        return {k: dict(v) for k, v in self.literature_search.items()}

    def save_literature_searches(self, rows: list[dict]) -> None:
        now = _now()
        for r in rows:
            old = self.literature_search.get((r["db"], r["query"])) or {}
            done_at = None
            if r["done"]:
                kept = old.get("look_back_done_at") and old.get("look_back_from") == r["look_back_from"]
                done_at = old["look_back_done_at"] if kept else now
            self.literature_search[(r["db"], r["query"])] = {
                "db": r["db"], "query": r["query"], "kind": r["kind"], "look_back_from": r["look_back_from"],
                "history_until": r["history_until"], "look_back_done_at": done_at, "last_searched_at": now}

    def insert_document(self, doc: dict) -> str | None:
        if doc["external_id"] in self.known_external_ids(doc["source_id"]):
            return None
        did = _id()
        self.document[did] = {**doc, "id": did, "first_seen_at": _now()}
        return did

    def insert_attachment(self, att: dict) -> str:
        aid = _id()
        self.attachment[aid] = {**att, "id": aid}
        return aid

    def insert_document_text(self, document_id: str, attachment_id: str | None, text: str) -> None:
        self.document_text.append({"document_id": document_id, "attachment_id": attachment_id,
                                   "text": text})

    def insert_match(self, m: dict) -> None:
        self.match.append(dict(m))

    # ───────────────────────────── watchlist ─────────────────────────────
    def class_enabled(self, ingredient_id: str, class_id: str) -> bool:
        """Whether the class's words are searched for this ingredient (ingredient_class.enabled)."""
        return bool(self.ingredient_class_state.get((ingredient_id, class_id), {}).get("enabled", True))

    def _searched_links(self) -> list[tuple[str, str]]:
        """The (ingredient, class) links of watched ingredients whose class words are searched."""
        return [(i, c) for i, c in self.ingredient_class
                if self.ingredient.get(i, {}).get("active", True) and self.class_enabled(i, c)]

    def load_terms(self) -> list[Term]:
        active = {i for i, r in self.ingredient.items() if r.get("active", True)}
        active_classes = {c for _, c in self._searched_links()}
        return [t for t in self.terms
                if (t.ingredient_id and t.ingredient_id in active)
                or (t.class_id and not t.ingredient_id and t.class_id in active_classes)]

    def class_ingredients(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for ing, cls in self._searched_links():
            out.setdefault(cls, []).append(ing)
        return out

    def active_ingredients(self) -> list[dict]:
        return [dict(r, id=i) for i, r in self.ingredient.items() if r.get("active", True)]

    def class_words(self, lang: str = "en") -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for ing, cls in self._searched_links():
            row = self.ingredient.get(ing)
            if row is None:
                continue
            words = sorted(t.term for t in self.terms if t.is_class and t.class_id == cls and t.lang == lang)
            if words:
                out[row["inn_en"]] = sorted({*out.get(row["inn_en"], []), *words})
        return out

    def ingredients_without_spc(self) -> list[str]:
        return [i for i, r in self.ingredient.items() if r.get("active", True) and i not in self.spc_mah]

    def mah_names(self, ingredient_ids: Iterable[str]) -> list[str]:
        return sorted({m for i in ingredient_ids for m in self.spc_mah.get(i, [])})

    # ───────────────────────────── issues ─────────────────────────────
    def _country(self, source_id: str) -> str | None:
        src = self.source.get(source_id) or {}
        return (self.regulator.get(src.get("regulator_id")) or {}).get("country_code")

    def candidate_issues(self, ingredient_ids: Iterable[str], date_from: date,
                         date_to: date) -> list[dict]:
        ids = set(ingredient_ids)
        out = []
        for iss in self.issue.values():
            if iss["first_date"] is None or not (date_from <= iss["first_date"] <= date_to):
                continue
            if iss["doc_type"] == "literature":
                continue  # a paper merges with nothing (merge.compatible)
            if not ids & {g for i, g in self.issue_ingredient if i == iss["id"]}:
                continue
            docs = []
            for link in self.issue_document:
                if link["issue_id"] != iss["id"] or link["method"] == "suggested":
                    continue
                d = self.document[link["document_id"]]
                text = "\n".join(t["text"] for t in self.document_text if t["document_id"] == d["id"])
                docs.append({"id": d["id"], "source_id": d["source_id"], "url": d["url"],
                             "title_orig": d["title_orig"], "doc_type": d["doc_type"],
                             "published_date": d["published_date"], "structured": d.get("structured"),
                             "country_code": self._country(d["source_id"]), "link": link["link"],
                             "method": link["method"], "text": text})
            out.append({"id": iss["id"], "doc_type": iss["doc_type"], "first_date": iss["first_date"],
                        "class_only": iss["class_only"],
                        "anchor_document_id": iss["anchor_document_id"], "documents": docs})
        return out

    def create_issue(self, *, doc_type: str, title: str, anchor_document_id: str,
                     first_date: date | None, class_only: bool, is_backfill: bool) -> str:
        iid = _id()
        self.issue[iid] = {"id": iid, "doc_type": doc_type, "title": title,
                           "anchor_document_id": anchor_document_id, "first_date": first_date,
                           "status": "new", "class_only": class_only, "is_backfill": is_backfill,
                           "created_at": _now()}
        return iid

    def link_document(self, issue_id: str, document_id: str, *, link: str, method: str,
                      score: int | None) -> None:
        if any(x["issue_id"] == issue_id and x["document_id"] == document_id
               for x in self.issue_document):
            return
        self.issue_document.append({"issue_id": issue_id, "document_id": document_id,
                                    "link": link, "method": method, "score": score})

    def set_issue_anchor(self, issue_id: str, document_id: str, *, title: str, doc_type: str,
                         first_date: date | None, is_backfill: bool = True) -> None:
        for x in self.issue_document:
            if x["issue_id"] == issue_id and x["link"] == "anchor" and x["document_id"] != document_id:
                x["link"] = "copy"
        iss = self.issue[issue_id]
        if iss["is_backfill"] and not is_backfill:
            iss["current_since"] = _now()
        iss.update(anchor_document_id=document_id, title=title, doc_type=doc_type,
                   is_backfill=iss["is_backfill"] and is_backfill)
        if first_date and (iss["first_date"] is None or first_date < iss["first_date"]):
            iss["first_date"] = first_date

    def mark_issue_current(self, issue_id: str) -> None:
        iss = self.issue[issue_id]
        if iss["is_backfill"]:
            iss.update(is_backfill=False, current_since=_now())

    def add_issue_ingredients(self, issue_id: str, ingredient_ids: Iterable[str]) -> None:
        for g in ingredient_ids:
            if (issue_id, g) not in self.issue_ingredient:
                self.issue_ingredient.append((issue_id, g))

    def documents_of(self, issue_id: str) -> list[dict]:
        return [x for x in self.issue_document if x["issue_id"] == issue_id]

    # ───────────────────────────── alerts ─────────────────────────────
    def issue_for_alert(self, issue_id: str) -> dict | None:
        iss = self.issue.get(issue_id)
        if not iss:
            return None
        d = self.document[iss["anchor_document_id"]]
        src = self.source.get(d["source_id"]) or {}
        reg = self.regulator.get(src.get("regulator_id")) or {}
        ing_ids = [g for i, g in self.issue_ingredient if i == issue_id]
        return {**iss, "document_id": d["id"], "url": d["url"], "title_orig": d["title_orig"],
                "lang": d.get("lang"), "country_name": reg.get("country_name"),
                "regulator_name": reg.get("name"), "source_kind": src.get("kind"), "ingredient_ids": ing_ids,
                "ingredients": sorted(self.ingredient[g]["inn_en"] for g in ing_ids
                                      if g in self.ingredient),
                "attachments": [a for a in self.attachment.values() if a["document_id"] == d["id"]]}

    def subscribers(self, kind: str, ingredient_ids: Iterable[str] | None = None) -> list[dict]:
        ids = set(ingredient_ids or [])
        seen, out = set(), []
        for s in self.subscription:
            p = self.person.get(s["person_id"])
            if s["kind"] != kind or not p or not p.get("active", True) or not p.get("telegram_chat_id"):
                continue
            if kind == "ingredient" and s.get("ingredient_id") not in (None, *ids):
                continue
            if kind == "admin_health" and p.get("role") != "admin":
                continue
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            out.append({"person_id": p["id"], "full_name": p["full_name"],
                        "telegram_chat_id": p["telegram_chat_id"], "role": p.get("role")})
        return out

    def admins(self) -> list[dict]:
        return [{"person_id": p["id"], "full_name": p["full_name"], "telegram_chat_id": p["telegram_chat_id"],
                 "role": p.get("role")}
                for p in self.person.values()
                if p.get("role") == "admin" and p.get("active", True) and p.get("telegram_chat_id")]

    def reminder_people(self) -> list[dict]:
        return [{"person_id": p["id"], "full_name": p["full_name"], "telegram_chat_id": p["telegram_chat_id"],
                 "role": p.get("role")}
                for p in self.person.values()
                if p.get("role") in ("admin", "reviewer") and p.get("active", True) and p.get("telegram_chat_id")]

    def eda_reminders(self, today: date, within_days: int = 2) -> list[dict]:
        """v_eda_clock in memory: a notice whose latest decision (self.review_event) is Concerns us and for which
        no authority_report not withdrawn exists (whatever decision it answered: a report sent is never
        forgotten, 0050); day zero is the Cairo day PHAROS first showed the notice, the day its row was created."""
        days = int(self.app_setting.get("eda_days") or 5)
        out = []
        for iid, iss in self.issue.items():
            decisions = sorted((e for e in self.review_event if e["issue_id"] == iid), key=lambda e: e["created_at"])
            if not decisions or decisions[-1]["to_status"] != "relevant":
                continue
            if any(a["issue_id"] == iid and a.get("withdrawn_at") is None for a in self.authority_report):
                continue
            anchor = self.document.get(iss.get("anchor_document_id")) or {}
            day_zero = iss["created_at"].astimezone(ZoneInfo("Africa/Cairo")).date()
            due = day_zero + timedelta(days=days)
            if due > today + timedelta(days=within_days):
                continue
            ing_ids = [g for i, g in self.issue_ingredient if i == iid]
            ing = self.ingredient.get(ing_ids[0]) if ing_ids else None
            src = self.source.get(anchor.get("source_id")) or {}
            reg = self.regulator.get(src.get("regulator_id")) or {}
            out.append({"issue_id": iid, "ingredient_id": ing_ids[0] if ing_ids else None,
                        "ingredient": (ing or {}).get("inn_en"), "title": iss["title"],
                        "country": reg.get("country_name"), "day_zero": day_zero, "due": due,
                        "days_left": (due - today).days, "clock": "late" if today > due else "running"})
        out.sort(key=lambda r: (r["due"], (r["title"] or "").lower(), r["issue_id"]))
        return out

    def notified(self, person_id: str, issue_id: str, kind: str) -> bool:
        return any(n["person_id"] == person_id and n["issue_id"] == issue_id and n["kind"] == kind
                   and (n["error"] is None or n.get("tg_message_id")) for n in self.notification)

    def notified_since(self, person_id: str, kind: str, since: datetime) -> bool:
        return any(n["person_id"] == person_id and n["kind"] == kind and n["sent_at"] >= since
                   and (n["error"] is None or n.get("tg_message_id")) for n in self.notification)

    def told_since(self, kind: str, since: datetime, *, dry_run: bool = False) -> set[str]:
        return {n["person_id"] for n in self.notification
                if n["kind"] == kind and n.get("issue_id") is None and n.get("person_id")
                and n["sent_at"] >= since and (n.get("error") is None or n.get("tg_message_id"))
                and (dry_run or not n.get("dry_run"))}

    def new_item_counts(self, since: datetime, until: datetime) -> list[dict]:
        """new_items() in memory: no history, no label watch, no literature."""
        counts: dict[str, int] = {}
        for d in self.document.values():
            src = self.source.get(d["source_id"]) or {}
            if (d.get("is_backfill") or src.get("kind") in ("spc", "literature")
                    or not (since <= d["first_seen_at"] < until)):
                continue
            country = (self.regulator.get(src.get("regulator_id")) or {}).get("country_name")
            counts[country] = counts.get(country, 0) + 1
        return [{"country_name": c, "n": n} for c, n in sorted(counts.items(), key=lambda x: x[0] or "")]

    def insert_notification(self, **fields: Any) -> None:
        self.notification.append({**fields, "sent_at": _now()})

    def last_notification_at(self, kind: str, *, delivered_only: bool = False,
                             before: datetime | None = None) -> datetime | None:
        times = [n["sent_at"] for n in self.notification
                 if n["kind"] == kind and not (delivered_only and n.get("error"))
                 and (before is None or n["sent_at"] < before)]
        return max(times) if times else None

    def refused_people(self, kind: str, since: datetime) -> list[str]:
        recent = [n for n in self.notification if n["kind"] == kind and n["sent_at"] >= since]
        got = {(n["person_id"], n["issue_id"]) for n in recent
               if not n.get("error") or n.get("tg_message_id")}
        return sorted({n["person_id"] for n in recent
                       if n.get("error") and not n.get("tg_message_id") and n["person_id"]
                       and (n["person_id"], n["issue_id"]) not in got})

    def refused_alerts(self, since: datetime) -> dict[str, set[str]]:
        rows = [n for n in self.notification
                if n["kind"] == "immediate" and n["issue_id"] and n["person_id"]]
        got = {(n["person_id"], n["issue_id"]) for n in rows
               if not n.get("error") or n.get("tg_message_id")}
        first: dict[tuple, datetime] = {}
        for n in rows:
            key = (n["person_id"], n["issue_id"])
            first[key] = min(first.get(key, n["sent_at"]), n["sent_at"])
        out: dict[str, set[str]] = {}
        for (person, issue), at in first.items():
            if at >= since and (person, issue) not in got:
                out.setdefault(issue, set()).add(person)
        return out

    def class_only_issues_since(self, since: datetime) -> list[str]:
        def paper(r: dict) -> bool:                       # papers: never on Telegram
            d = self.document.get(r["anchor_document_id"]) or {}
            return r.get("doc_type") == "literature" or (self.source.get(d.get("source_id")) or {}).get(
                "kind") == "literature"

        rows = [(r.get("current_since") or r["created_at"], i) for i, r in self.issue.items()
                if r["class_only"] and not r["is_backfill"] and not paper(r)
                and (r["created_at"] > since or (r.get("current_since") or r["created_at"]) > since)]
        return [i for _, i in sorted(rows, reverse=True)]

    # ───────────────────────────── drug classes ─────────────────────────────
    def ingredients_for_classes(self) -> list[dict]:
        out = []
        for i, r in sorted(self.ingredient.items(), key=lambda kv: kv[1].get("inn_en", "")):
            if not r.get("active", True) or not r.get("atc_code"):
                continue
            codes = [self.drug_class[c]["code"] for g, c in self.ingredient_class if g == i and c in self.drug_class]
            out.append({"id": i, "inn_en": r.get("inn_en"), "atc_code": r["atc_code"], "class_codes": codes})
        return out

    def drug_class_id(self, code: str) -> str | None:
        return next((i for i, c in self.drug_class.items() if c["code"] == code), None)

    def create_drug_class(self, *, code: str, name_en: str, wikidata_qid: str | None,
                          terms: Iterable[dict]) -> str:
        existing = self.drug_class_id(code)
        if existing:
            return existing
        cid = _id()
        self.drug_class[cid] = {"code": code, "name_en": name_en, "origin": "atc", "wikidata_qid": wikidata_qid}
        seen = set()
        for t in terms:
            if (t["lang"], t["term"]) in seen:
                continue
            seen.add((t["lang"], t["term"]))
            tid = _id()
            self.terms.append(Term(id=tid, term=t["term"], lang=t["lang"], mode=t["mode"], class_id=cid,
                                   kind="class"))
            self.term_state[tid] = {"changed_at": _now(), "rematched_at": None, "source": t["source"]}
        return cid

    def link_ingredient_class(self, ingredient_id: str, class_id: str, *, relation: str = "group",
                              enabled: bool = True) -> None:
        if (ingredient_id, class_id) in self.ingredient_class:
            return  # a link that exists is never changed
        if relation == "group" and self.drug_class.get(class_id, {}).get("origin") == "hand":
            relation = "manual"  # the database trigger ingredient_class_relation (0049)
        self.ingredient_class.append((ingredient_id, class_id))
        self.ingredient_class_state[(ingredient_id, class_id)] = {"relation": relation, "enabled": enabled}

    def set_class_search(self, ingredient_id: str, class_id: str, enabled: bool) -> None:
        """The app's set_class_search(): switching a class on again makes its words due for the check of the
        past (trigger class_search_enabled_again)."""
        if (ingredient_id, class_id) not in self.ingredient_class:
            raise KeyError("That class is not linked to this ingredient.")
        st = self.ingredient_class_state.setdefault((ingredient_id, class_id), {"relation": "group", "enabled": True})
        if enabled and not st["enabled"]:
            for t in self.terms:
                if t.is_class and t.class_id == class_id:
                    self.term_state.setdefault(t.id, {"rematched_at": None, "source": None})["changed_at"] = _now()
        st["enabled"] = enabled

    # ───────────────────────────── the check of the past ─────────────────────────────
    def _due(self, term_id: str) -> bool:
        st = self.term_state.get(term_id)
        return st is not None and (st.get("rematched_at") is None or st["rematched_at"] < st["changed_at"])

    def rematch_open_job(self) -> dict | None:
        return next((dict(j) for j in self.rematch_job.values() if j["finished_at"] is None), None)

    def rematch_due_terms(self) -> tuple[list[str], list[str]]:
        active = {t.id for t in self.load_terms()}
        ing = sorted(t.id for t in self.terms if t.ingredient_id and t.id in active and self._due(t.id))
        cls = sorted(t.id for t in self.terms if t.is_class and t.id in active and self._due(t.id))
        return ing, cls

    def rematch_create_job(self, *, since: date, ingredient_term_ids: list[str], class_term_ids: list[str],
                           trigger: str) -> dict:
        if self.rematch_open_job():
            raise RuntimeError("a check of the past is already open")
        jid = _id()
        self.rematch_job[jid] = {"id": jid, "trigger": trigger, "started_at": _now(), "since": since,
                                 "ingredient_term_ids": list(ingredient_term_ids),
                                 "class_term_ids": list(class_term_ids), "cursor_document_id": None,
                                 "documents_checked": 0, "documents_reread": 0, "documents_matched": 0,
                                 "issues_created": 0, "finished_at": None}
        return dict(self.rematch_job[jid])

    def rematch_terms(self, ingredient_term_ids: list[str], class_term_ids: list[str]) -> list[Term]:
        active_ing = {i for i, r in self.ingredient.items() if r.get("active", True)}
        wanted_i, wanted_c = set(ingredient_term_ids), set(class_term_ids)
        return [t for t in self.terms
                if (t.ingredient_id and t.id in wanted_i and t.ingredient_id in active_ing)
                or (t.is_class and t.id in wanted_c)]

    def rematch_documents(self, *, since: date, before: datetime, after_id: str | None,
                          limit: int) -> list[dict]:
        rows = []
        for d in sorted(self.document.values(), key=lambda x: x["id"]):
            src = self.source.get(d["source_id"]) or {}
            if src.get("kind", "safety") in ("spc", "literature") or d["first_seen_at"] >= before:
                continue
            when = d.get("published_date") or d["first_seen_at"].date()
            if when < since or (after_id is not None and d["id"] <= after_id):
                continue
            rows.append(d)
            if len(rows) >= limit:
                break
        out = []
        for d in rows:
            links = [x for x in self.issue_document if x["document_id"] == d["id"] and x["method"] != "suggested"]
            links.sort(key=lambda x: self.issue[x["issue_id"]]["anchor_document_id"] != d["id"])
            iss = self.issue[links[0]["issue_id"]] if links else None
            src = self.source.get(d["source_id"]) or {}
            out.append({
                "id": d["id"], "source_id": d["source_id"], "url": d["url"], "title_orig": d["title_orig"],
                "lang": d.get("lang"), "doc_type": d["doc_type"], "published_date": d.get("published_date"),
                "structured": d.get("structured"), "r2_key": d.get("r2_key"), "mime": d.get("mime"),
                "parser": src.get("parser"), "country_code": self._country(d["source_id"]),
                "texts": [{"attachment_id": t["attachment_id"], "text": t["text"]}
                          for t in self.document_text if t["document_id"] == d["id"]],
                "attachments": [dict(a) for a in self.attachment.values() if a["document_id"] == d["id"]],
                "matched_terms": {m.get("term_id") or m.get("class_term_id") for m in self.match
                                  if m["document_id"] == d["id"] and (m.get("term_id") or m.get("class_term_id"))},
                "issue": {"id": iss["id"], "class_only": iss["class_only"]} if iss else None,
                "shared_original": bool(d.get("r2_key")) and sum(
                    1 for x in self.document.values() if x.get("r2_key") == d["r2_key"]) > 1,
            })
        return out

    def rematch_advance(self, job_id: str, *, cursor: str, checked: int = 0, reread: int = 0,
                        matched: int = 0, issues_created: int = 0) -> None:
        j = self.rematch_job[job_id]
        j["cursor_document_id"] = cursor
        j["documents_checked"] += checked
        j["documents_reread"] += reread
        j["documents_matched"] += matched
        j["issues_created"] += issues_created

    def rematch_finish(self, job_id: str) -> None:
        j = self.rematch_job[job_id]
        j["finished_at"] = _now()
        for tid in j["ingredient_term_ids"] + j["class_term_ids"]:
            st = self.term_state.get(tid)
            if st is not None and st["changed_at"] <= j["started_at"]:
                st["rematched_at"] = j["started_at"]

    def set_issue_names_ingredient(self, issue_id: str) -> None:
        self.issue[issue_id]["class_only"] = False

    # ───────────────────────────── probe ─────────────────────────────
    def get_probe(self, probe_id: str) -> dict | None:
        return self.probe_result.get(probe_id)

    def update_probe(self, probe_id: str, **fields: Any) -> None:
        self.probe_result.setdefault(probe_id, {"id": probe_id}).update(fields)
