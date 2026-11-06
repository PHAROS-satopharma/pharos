"""Every SQL statement the pipeline runs, behind one small interface.

``Store`` talks to Postgres through ``Db``. ``collectors.core.memstore.MemoryStore`` implements the same
methods in memory for fixture tests and ``--no-db`` local runs, so the runner, merging and alerts never
contain SQL themselves.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable

from collectors.core.db import Db, jsonb
from collectors.core.models import SourceConfig
from collectors.matching import Term

DEFAULT_SETTINGS: dict[str, Any] = {
    "telegram_dry_run": True,
    "digest_hour_cairo": 9,
    "backfill_months": 12,
}


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _job(row: dict) -> dict:
    return {**row, "id": str(row["id"]),
            "ingredient_term_ids": [str(x) for x in row.get("ingredient_term_ids") or []],
            "class_term_ids": [str(x) for x in row.get("class_term_ids") or []],
            "cursor_document_id": str(row["cursor_document_id"]) if row.get("cursor_document_id") else None}


class Store:
    def __init__(self, db: Db) -> None:
        self.db = db

    def transaction(self):
        return self.db.transaction()

    # ───────────────────────────── settings ─────────────────────────────
    def settings(self) -> dict[str, Any]:
        out = dict(DEFAULT_SETTINGS)
        for row in self.db.fetchall("select key, value from app_setting"):
            out[row["key"]] = _decode(row["value"])
        return out

    # ───────────────────────────── catalogue ─────────────────────────────
    def upsert_regulator(self, reg: dict) -> None:
        self.db.execute(
            """insert into regulator (id, country_code, country_name, name, languages, homepage)
               values (%(id)s, %(country_code)s, %(country_name)s, %(name)s, %(languages)s, %(homepage)s)
               on conflict (id) do update set country_code = excluded.country_code,
                 country_name = excluded.country_name, name = excluded.name,
                 languages = excluded.languages, homepage = excluded.homepage""",
            reg)

    def upsert_catalogue_source(self, src: SourceConfig, notes: str | None) -> None:
        """Insert or refresh an origin='catalogue' row. Rows a person added (origin='user') are never
        touched, and ``enabled`` is only set on insert: switching a source off is an admin's call."""
        self.db.execute(
            """insert into source (id, regulator_id, kind, channel, url, parser, languages, schedule,
                                   enabled, origin, expected_max_gap_days, notes, page_url)
               values (%(id)s, %(regulator_id)s, %(kind)s, %(channel)s, %(url)s, %(parser)s,
                       %(languages)s, %(schedule)s, %(enabled)s, 'catalogue', %(gap)s, %(notes)s,
                       %(page)s)
               on conflict (id) do update set regulator_id = excluded.regulator_id,
                 kind = excluded.kind, channel = excluded.channel, url = excluded.url,
                 parser = excluded.parser, languages = excluded.languages,
                 schedule = excluded.schedule, expected_max_gap_days = excluded.expected_max_gap_days,
                 notes = excluded.notes, page_url = excluded.page_url
               where source.origin = 'catalogue'""",
            {"id": src.id, "regulator_id": src.regulator_id, "kind": src.kind,
             "channel": src.channel, "url": src.url, "parser": src.parser,
             "languages": src.languages, "schedule": src.schedule, "enabled": src.enabled,
             "gap": src.expected_max_gap_days, "notes": notes, "page": src.page_url})

    def list_sources(self) -> list[dict]:
        return self.db.fetchall("select * from source order by id")

    def get_source(self, source_id: str) -> dict | None:
        return self.db.fetchone("select * from source where id = %(id)s", {"id": source_id})

    def country_code(self, regulator_id: str) -> str | None:
        row = self.db.fetchone("select country_code from regulator where id = %(i)s",
                               {"i": regulator_id})
        return row["country_code"] if row else None

    # ───────────────────────────── runs ─────────────────────────────
    def create_run(self, trigger: str, git_sha: str | None, schedule: str | None = None) -> str:
        row = self.db.fetchone(
            "insert into run (trigger, git_sha, schedule) values (%(t)s, %(g)s, %(s)s) returning id",
            {"t": trigger, "g": git_sha, "s": schedule})
        return str(row["id"])

    def finish_run(self, run_id: str, ok: bool) -> None:
        self.db.execute("update run set finished_at = now(), ok = %(ok)s where id = %(id)s",
                        {"ok": ok, "id": run_id})

    def start_source_run(self, run_id: str, source_id: str) -> str:
        row = self.db.fetchone(
            "insert into source_run (run_id, source_id) values (%(r)s, %(s)s) returning id",
            {"r": run_id, "s": source_id})
        return str(row["id"])

    def finish_source_run(self, source_run_id: str, *, http_status: int | None, items_seen: int,
                          items_new: int, items_matched: int, error: str | None,
                          duration_ms: int) -> None:
        self.db.execute(
            """update source_run set finished_at = now(), http_status = %(h)s, items_seen = %(s)s,
                 items_new = %(n)s, items_matched = %(m)s, error = %(e)s, duration_ms = %(d)s
               where id = %(id)s""",
            {"h": http_status, "s": items_seen, "n": items_new, "m": items_matched,
             "e": error, "d": duration_ms, "id": source_run_id})

    def set_source_state(self, source_id: str, *, health: str, consecutive_failures: int,
                         ok: bool = False, last_item_at: datetime | None = None) -> None:
        self.db.execute(
            """update source set health = %(h)s, consecutive_failures = %(f)s,
                 last_ok_at = case when %(ok)s then now() else last_ok_at end,
                 last_item_at = greatest(last_item_at, %(li)s)
               where id = %(id)s""",
            {"h": health, "f": consecutive_failures, "ok": ok, "li": last_item_at, "id": source_id})

    # ───────────────────────────── documents ─────────────────────────────
    def known_external_ids(self, source_id: str) -> set[str]:
        rows = self.db.fetchall("select external_id from document where source_id = %(s)s",
                                {"s": source_id})
        return {r["external_id"] for r in rows}

    def insert_document(self, doc: dict) -> str | None:
        row = self.db.fetchone(
            """insert into document (source_id, external_id, url, title_orig, lang, doc_type,
                 published_date, sha256, r2_key, mime, bytes, extraction, structured, is_backfill)
               values (%(source_id)s, %(external_id)s, %(url)s, %(title_orig)s, %(lang)s,
                 %(doc_type)s, %(published_date)s, %(sha256)s, %(r2_key)s, %(mime)s, %(bytes)s,
                 %(extraction)s, %(structured)s, %(is_backfill)s)
               on conflict (source_id, external_id) do nothing returning id""",
            {**doc, "structured": jsonb(doc.get("structured")) if doc.get("structured") is not None
             else None})
        return str(row["id"]) if row else None

    def insert_attachment(self, att: dict) -> str:
        row = self.db.fetchone(
            """insert into attachment (document_id, url, filename, sha256, r2_key, mime, bytes,
                 extraction, words)
               values (%(document_id)s, %(url)s, %(filename)s, %(sha256)s, %(r2_key)s, %(mime)s,
                 %(bytes)s, %(extraction)s, %(words)s)
               on conflict (document_id, url) do update set sha256 = excluded.sha256
               returning id""", att)
        return str(row["id"])

    def insert_document_text(self, document_id: str, attachment_id: str | None, text: str) -> None:
        self.db.execute(
            "insert into document_text (document_id, attachment_id, text) values (%(d)s, %(a)s, %(t)s)",
            {"d": document_id, "a": attachment_id, "t": text.replace("\x00", "")})

    def insert_match(self, m: dict) -> None:
        self.db.execute(
            """insert into match (document_id, attachment_id, ingredient_id, class_id, term_id,
                 class_term_id, field, start_offset, end_offset, matched_text, snippet, confidence)
               values (%(document_id)s, %(attachment_id)s, %(ingredient_id)s, %(class_id)s,
                 %(term_id)s, %(class_term_id)s, %(field)s, %(start_offset)s, %(end_offset)s,
                 %(matched_text)s, %(snippet)s, %(confidence)s)""", m)

    # ───────────────────────────── watchlist ─────────────────────────────
    def load_terms(self) -> list[Term]:
        rows = self.db.fetchall(
            """select t.id, t.term, t.lang, t.mode::text as mode, t.exclusions, t.ingredient_id,
                      t.kind::text as kind
                 from ingredient_term t join ingredient i on i.id = t.ingredient_id
                where i.active""")
        terms = [Term(id=str(r["id"]), term=r["term"], lang=r["lang"], mode=r["mode"],
                      exclusions=tuple(r["exclusions"] or ()), ingredient_id=str(r["ingredient_id"]),
                      kind=r["kind"]) for r in rows]
        rows = self.db.fetchall(
            """select ct.id, ct.term, ct.lang, ct.mode::text as mode, ct.exclusions, ct.class_id
                 from class_term ct
                where exists (select 1 from ingredient_class ic join ingredient i
                                on i.id = ic.ingredient_id
                               where ic.class_id = ct.class_id and i.active)""")
        terms += [Term(id=str(r["id"]), term=r["term"], lang=r["lang"], mode=r["mode"],
                       exclusions=tuple(r["exclusions"] or ()), class_id=str(r["class_id"]),
                       kind="class") for r in rows]
        return terms

    def class_ingredients(self) -> dict[str, list[str]]:
        rows = self.db.fetchall(
            """select ic.class_id, ic.ingredient_id from ingredient_class ic
                 join ingredient i on i.id = ic.ingredient_id where i.active""")
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(str(r["class_id"]), []).append(str(r["ingredient_id"]))
        return out

    def active_ingredients(self) -> list[dict]:
        return self.db.fetchall(
            "select id, inn_en, atc_code from ingredient where active order by inn_en")

    def ingredients_without_spc(self) -> list[str]:
        rows = self.db.fetchall(
            """select i.id from ingredient i
                where i.active and not exists (select 1 from spc_product p where p.ingredient_id = i.id)""")
        return [str(r["id"]) for r in rows]

    def mah_names(self, ingredient_ids: Iterable[str]) -> list[str]:
        ids = list(ingredient_ids)
        if not ids:
            return []
        rows = self.db.fetchall(
            """select distinct mah from spc_product
                where ingredient_id = any(%(ids)s::uuid[]) and mah is not null and mah <> ''""",
            {"ids": ids})
        return [r["mah"] for r in rows]

    # ───────────────────────────── issues ─────────────────────────────
    def candidate_issues(self, ingredient_ids: Iterable[str], date_from: date,
                         date_to: date) -> list[dict]:
        """Issues sharing an ingredient whose first date falls in the window, with their documents
        (and each document's stored text) for scoring."""
        ids = list(ingredient_ids)
        if not ids:
            return []
        issues = self.db.fetchall(
            """select i.id, i.doc_type::text as doc_type, i.first_date, i.class_only,
                      i.anchor_document_id
                 from issue i
                where i.first_date between %(f)s and %(t)s
                  and exists (select 1 from issue_ingredient ii
                               where ii.issue_id = i.id and ii.ingredient_id = any(%(ids)s::uuid[]))""",
            {"f": date_from, "t": date_to, "ids": ids})
        out = []
        for iss in issues:
            docs = self.db.fetchall(
                """select d.id, d.source_id, d.url, d.title_orig, d.doc_type::text as doc_type,
                          d.published_date, d.structured, r.country_code, idd.link::text as link,
                          idd.method::text as method,
                          coalesce((select string_agg(dt.text, E'\n') from document_text dt
                                     where dt.document_id = d.id), '') as text
                     from issue_document idd
                     join document d on d.id = idd.document_id
                     join source s on s.id = d.source_id
                     join regulator r on r.id = s.regulator_id
                    where idd.issue_id = %(i)s and idd.method <> 'suggested'""",
                {"i": iss["id"]})
            out.append({**iss, "id": str(iss["id"]),
                        "anchor_document_id": str(iss["anchor_document_id"])
                        if iss["anchor_document_id"] else None,
                        "documents": [{**d, "id": str(d["id"])} for d in docs]})
        return out

    def create_issue(self, *, doc_type: str, title: str, anchor_document_id: str,
                     first_date: date | None, class_only: bool, is_backfill: bool) -> str:
        row = self.db.fetchone(
            """insert into issue (doc_type, title, anchor_document_id, first_date, class_only,
                 is_backfill)
               values (%(dt)s, %(t)s, %(a)s, %(f)s, %(c)s, %(b)s) returning id""",
            {"dt": doc_type, "t": title, "a": anchor_document_id, "f": first_date,
             "c": class_only, "b": is_backfill})
        return str(row["id"])

    def link_document(self, issue_id: str, document_id: str, *, link: str, method: str,
                      score: int | None) -> None:
        self.db.execute(
            """insert into issue_document (issue_id, document_id, link, method, score)
               values (%(i)s, %(d)s, %(l)s, %(m)s, %(s)s)
               on conflict (issue_id, document_id) do nothing""",
            {"i": issue_id, "d": document_id, "l": link, "m": method, "s": score})

    def set_issue_anchor(self, issue_id: str, document_id: str, *, title: str, doc_type: str,
                         first_date: date | None, is_backfill: bool = True) -> None:
        """An EMA anchor arrived after its national copies: it becomes the issue's anchor (a fresh one
        takes the issue out of the backfill, so it alerts)."""
        self.db.execute(
            """update issue_document set link = 'copy'
                where issue_id = %(i)s and link = 'anchor' and document_id <> %(d)s""",
            {"i": issue_id, "d": document_id})
        self.db.execute(
            """update issue set anchor_document_id = %(d)s, title = %(t)s, doc_type = %(dt)s,
                 first_date = least(first_date, %(f)s), is_backfill = is_backfill and %(b)s,
                 current_since = case when is_backfill and not %(b)s then now() else current_since end,
                 updated_at = now() where id = %(i)s""",
            {"d": document_id, "t": title, "dt": doc_type, "f": first_date, "b": is_backfill,
             "i": issue_id})

    def mark_issue_current(self, issue_id: str) -> None:
        """A fresh document joined a history issue: it leaves the history, so it alerts and shows."""
        self.db.execute(
            """update issue set is_backfill = false, current_since = now(), updated_at = now()
                where id = %(i)s and is_backfill""",
            {"i": issue_id})

    def add_issue_ingredients(self, issue_id: str, ingredient_ids: Iterable[str]) -> None:
        for ing in ingredient_ids:
            self.db.execute(
                """insert into issue_ingredient (issue_id, ingredient_id) values (%(i)s, %(g)s)
                   on conflict do nothing""", {"i": issue_id, "g": ing})

    # ───────────────────────────── alerts ─────────────────────────────
    def issue_for_alert(self, issue_id: str) -> dict | None:
        row = self.db.fetchone(
            """select i.id, i.title, i.doc_type::text as doc_type, i.first_date, i.class_only,
                      i.is_backfill, d.id as document_id, d.url, d.title_orig, d.lang,
                      r.country_name, r.name as regulator_name,
                      (select array_agg(g.inn_en order by g.inn_en) from issue_ingredient ii
                         join ingredient g on g.id = ii.ingredient_id where ii.issue_id = i.id)
                        as ingredients
                 from issue i
                 join document d on d.id = i.anchor_document_id
                 join source s on s.id = d.source_id
                 join regulator r on r.id = s.regulator_id
                where i.id = %(i)s""", {"i": issue_id})
        if not row:
            return None
        row = dict(row)
        row["ingredient_ids"] = [str(r["ingredient_id"]) for r in self.db.fetchall(
            "select ingredient_id from issue_ingredient where issue_id = %(i)s", {"i": issue_id})]
        row["attachments"] = self.db.fetchall(
            """select url, filename, r2_key, mime, bytes from attachment
                where document_id = %(d)s order by bytes nulls last""", {"d": row["document_id"]})
        row["ingredients"] = row.get("ingredients") or []
        return row

    def subscribers(self, kind: str, ingredient_ids: Iterable[str] | None = None) -> list[dict]:
        ids = list(ingredient_ids or [])
        sql = """select distinct p.id as person_id, p.full_name, p.telegram_chat_id, p.role::text as role
                   from subscription s join person p on p.id = s.person_id
                  where s.kind = %(k)s and p.active and p.telegram_chat_id is not null"""
        params: dict[str, Any] = {"k": kind}
        if kind == "ingredient":
            sql += " and (s.ingredient_id is null or s.ingredient_id = any(%(ids)s::uuid[]))"
            params["ids"] = ids
        if kind == "admin_health":
            sql += " and p.role = 'admin'"
        rows = self.db.fetchall(sql, params)
        return [{**r, "person_id": str(r["person_id"])} for r in rows]

    def admins(self) -> list[dict]:
        """Every active admin with Telegram linked, whatever they subscribed to (the monthly report)."""
        rows = self.db.fetchall(
            """select p.id as person_id, p.full_name, p.telegram_chat_id, p.role::text as role
                 from person p
                where p.role = 'admin' and p.active and p.telegram_chat_id is not null
                order by p.created_at""")
        return [{**r, "person_id": str(r["person_id"])} for r in rows]

    def notified(self, person_id: str, issue_id: str, kind: str) -> bool:
        """Delivered, or at least its text was: a PDF refused after the text went out still has a
        message id, and sending the text again would repeat it."""
        return self.db.fetchone(
            """select 1 from notification where person_id = %(p)s and issue_id = %(i)s
                 and kind = %(k)s and (error is null or tg_message_id is not null) limit 1""",
            {"p": person_id, "i": issue_id, "k": kind}) is not None

    def notified_since(self, person_id: str, kind: str, since: datetime) -> bool:
        """A ``kind`` message (with no issue) reached this person since ``since``, or went as a dry run."""
        return self.db.fetchone(
            """select 1 from notification where person_id = %(p)s and kind = %(k)s and sent_at >= %(s)s
                 and (error is null or tg_message_id is not null) limit 1""",
            {"p": person_id, "k": kind, "s": since}) is not None

    def new_item_counts(self, since: datetime, until: datetime) -> list[dict]:
        """Per country, how many items the authorities published in [since, until) — new_items() in
        0032_sources_horizontal.sql, the very list the Sources screen shows."""
        rows = self.db.fetchall(
            """select country_name, count(*)::int as n from new_items(%(f)s, %(t)s)
                group by country_name order by country_name""", {"f": since, "t": until})
        return [{"country_name": r["country_name"], "n": int(r["n"])} for r in rows]

    def insert_notification(self, *, person_id: str | None, issue_id: str | None, kind: str,
                            dry_run: bool, tg_message_id: int | None, error: str | None,
                            summary: str) -> None:
        self.db.execute(
            """insert into notification (person_id, issue_id, kind, dry_run, tg_message_id, error,
                 summary)
               values (%(p)s, %(i)s, %(k)s, %(d)s, %(m)s, %(e)s, %(s)s)""",
            {"p": person_id, "i": issue_id, "k": kind, "d": dry_run, "m": tg_message_id,
             "e": error, "s": summary})

    def last_notification_at(self, kind: str, *, delivered_only: bool = False,
                             before: datetime | None = None) -> datetime | None:
        params: dict[str, Any] = {"k": kind}
        if before is not None:
            params["b"] = before
        row = self.db.fetchone(
            "select max(sent_at) as at from notification where kind = %(k)s"
            + (" and error is null" if delivered_only else "")
            + (" and sent_at < %(b)s" if before is not None else ""), params)
        return row["at"] if row else None

    def refused_people(self, kind: str, since: datetime) -> list[str]:
        """People with a ``kind`` message refused since ``since`` whose issue has not reached them since
        (per issue: a digest delivered only partway still owes them the rest)."""
        rows = self.db.fetchall(
            """select distinct n.person_id from notification n
                where n.kind = %(k)s and n.error is not null and n.tg_message_id is null
                  and n.sent_at >= %(s)s and n.person_id is not null
                  and not exists (select 1 from notification m
                                   where m.kind = n.kind and m.person_id = n.person_id
                                     and m.issue_id is not distinct from n.issue_id
                                     and (m.error is null or m.tg_message_id is not null)
                                     and m.sent_at >= %(s)s)""",
            {"k": kind, "s": since})
        return [str(r["person_id"]) for r in rows]

    def refused_alerts(self, since: datetime) -> dict[str, set[str]]:
        """Issue -> the people whose immediate alert was first refused since ``since`` and who never got
        it. The window counts from the FIRST refusal: every retry writes a new refused row, and counting
        from the latest one would retry a blocked bot for ever."""
        rows = self.db.fetchall(
            """select n.issue_id, n.person_id from notification n
                where n.kind = 'immediate' and n.issue_id is not null and n.person_id is not null
                group by n.issue_id, n.person_id
               having bool_and(n.error is not null and n.tg_message_id is null)
                  and min(n.sent_at) >= %(s)s""",
            {"s": since})
        out: dict[str, set[str]] = {}
        for r in rows:
            out.setdefault(str(r["issue_id"]), set()).add(str(r["person_id"]))
        return out

    def class_only_issues_since(self, since: datetime) -> list[str]:
        rows = self.db.fetchall(
            """select id from issue
                where class_only and not is_backfill and (created_at > %(s)s or current_since > %(s)s)
                order by coalesce(current_since, created_at) desc""", {"s": since})
        return [str(r["id"]) for r in rows]

    # ───────────────────────────── drug classes (collectors/classes.py) ─────────────────────────────
    def ingredients_for_classes(self) -> list[dict]:
        """Active ingredients with an ATC code, and the codes of the classes they belong to."""
        rows = self.db.fetchall(
            """select i.id, i.inn_en, i.atc_code,
                      coalesce(array_agg(c.code) filter (where c.code is not null), '{}') as class_codes
                 from ingredient i
                 left join ingredient_class ic on ic.ingredient_id = i.id
                 left join drug_class c on c.id = ic.class_id
                where i.active and i.atc_code is not null
                group by i.id order by i.inn_en""")
        return [{**r, "id": str(r["id"]), "class_codes": list(r["class_codes"] or [])} for r in rows]

    def drug_class_id(self, code: str) -> str | None:
        row = self.db.fetchone("select id from drug_class where code = %(c)s", {"c": code})
        return str(row["id"]) if row else None

    def create_drug_class(self, *, code: str, name_en: str, wikidata_qid: str | None,
                          terms: Iterable[dict]) -> str:
        """A class made from the ATC code, with its words. An existing class (same code) is never
        changed: its id is returned as it is."""
        with self.db.transaction():
            row = self.db.fetchone(
                """insert into drug_class (code, name_en, origin, wikidata_qid)
                   values (%(c)s, %(n)s, 'atc', %(q)s) on conflict (code) do nothing returning id""",
                {"c": code, "n": name_en, "q": wikidata_qid})
            if row is None:
                return self.drug_class_id(code) or ""
            class_id = str(row["id"])
            for t in terms:
                self.db.execute(
                    """insert into class_term (class_id, lang, term, mode, source)
                       values (%(c)s, %(l)s, %(t)s, %(m)s, %(s)s) on conflict (class_id, lang, term) do nothing""",
                    {"c": class_id, "l": t["lang"], "t": t["term"], "m": t["mode"], "s": t["source"]})
            return class_id

    def link_ingredient_class(self, ingredient_id: str, class_id: str) -> None:
        self.db.execute(
            """insert into ingredient_class (ingredient_id, class_id) values (%(i)s, %(c)s)
               on conflict do nothing""", {"i": ingredient_id, "c": class_id})

    # ───────────────────────────── the check of the past (collectors/rematch.py) ─────────────────────────────
    def rematch_open_job(self) -> dict | None:
        row = self.db.fetchone("select * from rematch_job where finished_at is null")
        return _job(row) if row else None

    def rematch_due_terms(self) -> tuple[list[str], list[str]]:
        """Words added or changed since they were last checked against the past (rematched_at older than
        changed_at, or never), of watched ingredients and of the classes those belong to."""
        ing = self.db.fetchall(
            """select t.id from ingredient_term t join ingredient i on i.id = t.ingredient_id
                where i.active and (t.rematched_at is null or t.rematched_at < t.changed_at)
                order by t.id""")
        cls = self.db.fetchall(
            """select ct.id from class_term ct
                where (ct.rematched_at is null or ct.rematched_at < ct.changed_at)
                  and exists (select 1 from ingredient_class ic join ingredient i on i.id = ic.ingredient_id
                               where ic.class_id = ct.class_id and i.active)
                order by ct.id""")
        return [str(r["id"]) for r in ing], [str(r["id"]) for r in cls]

    def rematch_create_job(self, *, since: date, ingredient_term_ids: list[str], class_term_ids: list[str],
                           trigger: str) -> dict:
        row = self.db.fetchone(
            """insert into rematch_job (trigger, since, ingredient_term_ids, class_term_ids)
               values (%(t)s, %(s)s, %(i)s::uuid[], %(c)s::uuid[]) returning *""",
            {"t": trigger, "s": since, "i": ingredient_term_ids, "c": class_term_ids})
        return _job(row)

    def rematch_terms(self, ingredient_term_ids: list[str], class_term_ids: list[str]) -> list[Term]:
        """The job's words as they are now (a word removed meanwhile is simply not there)."""
        rows = self.db.fetchall(
            """select t.id, t.term, t.lang, t.mode::text as mode, t.exclusions, t.ingredient_id,
                      t.kind::text as kind
                 from ingredient_term t join ingredient i on i.id = t.ingredient_id
                where i.active and t.id = any(%(ids)s::uuid[])""", {"ids": ingredient_term_ids})
        terms = [Term(id=str(r["id"]), term=r["term"], lang=r["lang"], mode=r["mode"],
                      exclusions=tuple(r["exclusions"] or ()), ingredient_id=str(r["ingredient_id"]),
                      kind=r["kind"]) for r in rows]
        rows = self.db.fetchall(
            """select ct.id, ct.term, ct.lang, ct.mode::text as mode, ct.exclusions, ct.class_id
                 from class_term ct where ct.id = any(%(ids)s::uuid[])""", {"ids": class_term_ids})
        terms += [Term(id=str(r["id"]), term=r["term"], lang=r["lang"], mode=r["mode"],
                       exclusions=tuple(r["exclusions"] or ()), class_id=str(r["class_id"]),
                       kind="class") for r in rows]
        return terms

    def rematch_documents(self, *, since: date, before: datetime, after_id: str | None,
                          limit: int) -> list[dict]:
        """The next stored notices to check, in id order after ``after_id``: dated ``since`` or later (the
        publication date, else the Cairo day it was first seen), first seen before the job started, not a
        label (SPC) or a literature record. Each comes with its kept text, its attachments, the words that
        already matched it and the issue it belongs to."""
        docs = self.db.fetchall(
            """select d.id, d.source_id, d.url, d.title_orig, d.lang, d.doc_type::text as doc_type,
                      d.published_date, d.structured, d.r2_key, d.mime, s.parser,
                      r.country_code
                 from document d
                 join source s on s.id = d.source_id
                 join regulator r on r.id = s.regulator_id
                where s.kind not in ('spc', 'literature')
                  and d.first_seen_at < %(b)s
                  and coalesce(d.published_date, (d.first_seen_at at time zone 'Africa/Cairo')::date) >= %(s)s
                  and (%(a)s::uuid is null or d.id > %(a)s::uuid)
                order by d.id
                limit %(n)s""",
            {"s": since, "b": before, "a": after_id, "n": limit})
        if not docs:
            return []
        ids = [str(d["id"]) for d in docs]
        texts: dict[str, list[dict]] = {}
        for r in self.db.fetchall(
                """select document_id, attachment_id, text from document_text
                    where document_id = any(%(ids)s::uuid[])""", {"ids": ids}):
            texts.setdefault(str(r["document_id"]), []).append(
                {"attachment_id": str(r["attachment_id"]) if r["attachment_id"] else None, "text": r["text"]})
        atts: dict[str, list[dict]] = {}
        for r in self.db.fetchall(
                """select id, document_id, url, r2_key, mime, extraction::text as extraction from attachment
                    where document_id = any(%(ids)s::uuid[]) order by document_id, id""", {"ids": ids}):
            atts.setdefault(str(r["document_id"]), []).append(
                {**r, "id": str(r["id"]), "document_id": str(r["document_id"])})
        matched: dict[str, set[str]] = {}
        for r in self.db.fetchall(
                """select document_id, coalesce(term_id, class_term_id) as term from match
                    where document_id = any(%(ids)s::uuid[]) and coalesce(term_id, class_term_id) is not null""",
                {"ids": ids}):
            matched.setdefault(str(r["document_id"]), set()).add(str(r["term"]))
        issues: dict[str, dict] = {}
        for r in self.db.fetchall(
                """select distinct on (idd.document_id) idd.document_id, i.id, i.class_only
                     from issue_document idd join issue i on i.id = idd.issue_id
                    where idd.document_id = any(%(ids)s::uuid[]) and idd.method <> 'suggested'
                    order by idd.document_id, coalesce(i.anchor_document_id = idd.document_id, false) desc,
                             i.created_at""",
                {"ids": ids}):
            issues[str(r["document_id"])] = {"id": str(r["id"]), "class_only": r["class_only"]}
        # An original several notices share (one list page for all its rows) is not a notice's own text.
        keys = sorted({d["r2_key"] for d in docs if d["r2_key"]})
        shared = {r["r2_key"] for r in self.db.fetchall(
            """select r2_key from document where r2_key = any(%(k)s) group by r2_key having count(*) > 1""",
            {"k": keys})} if keys else set()
        out = []
        for d in docs:
            k = str(d["id"])
            out.append({**d, "id": k, "texts": texts.get(k, []), "attachments": atts.get(k, []),
                        "matched_terms": matched.get(k, set()), "issue": issues.get(k),
                        "shared_original": d["r2_key"] in shared})
        return out

    def rematch_advance(self, job_id: str, *, cursor: str, checked: int = 0, reread: int = 0,
                        matched: int = 0, issues_created: int = 0) -> None:
        self.db.execute(
            """update rematch_job set cursor_document_id = %(c)s,
                 documents_checked = documents_checked + %(k)s, documents_reread = documents_reread + %(r)s,
                 documents_matched = documents_matched + %(m)s, issues_created = issues_created + %(i)s
               where id = %(j)s""",
            {"c": cursor, "k": checked, "r": reread, "m": matched, "i": issues_created, "j": job_id})

    def rematch_finish(self, job_id: str) -> None:
        """The job's words are checked as they were when it started; one changed since stays due."""
        with self.db.transaction():
            job = self.db.fetchone(
                "update rematch_job set finished_at = now() where id = %(j)s returning *", {"j": job_id})
            if not job:
                return
            self.db.execute(
                """update ingredient_term set rematched_at = %(at)s
                    where id = any(%(ids)s::uuid[]) and changed_at <= %(at)s""",
                {"at": job["started_at"], "ids": job["ingredient_term_ids"]})
            self.db.execute(
                """update class_term set rematched_at = %(at)s
                    where id = any(%(ids)s::uuid[]) and changed_at <= %(at)s""",
                {"at": job["started_at"], "ids": job["class_term_ids"]})

    def set_issue_names_ingredient(self, issue_id: str) -> None:
        """A class-only issue whose notice turns out to name a watched ingredient is no longer class-only."""
        self.db.execute("update issue set class_only = false, updated_at = now() where id = %(i)s and class_only",
                        {"i": issue_id})

    # ───────────────────────────── probe ─────────────────────────────
    def get_probe(self, probe_id: str) -> dict | None:
        return self.db.fetchone("select * from probe_result where id = %(i)s", {"i": probe_id})

    def update_probe(self, probe_id: str, **fields: Any) -> None:
        allowed = {"status", "channel_detected", "parser_detected", "items", "error", "finished_at"}
        sets, params = [], {"id": probe_id}
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(k)
            sets.append(f"{k} = %({k})s")
            params[k] = jsonb(v) if k == "items" else v
        if sets:
            self.db.execute(f"update probe_result set {', '.join(sets)} where id = %(id)s", params)
