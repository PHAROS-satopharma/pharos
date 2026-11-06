"""PHAROS weekly screening report: one Cairo week, Sunday to Saturday (Dr Sama's review, 6 Nov 2026).

Some findings must reach the Egyptian Drug Authority within 5 days, so the report covers one week and is made
every Sunday at 05:00 Cairo for the week that ended at midnight (``python -m collectors.report``; ``--week`` makes
any week again). It goes into her SOP and the pharmacovigilance system master file.

It is read from the same database functions as the app, so the report and the screens never disagree:

  ingredient_screen(), ingredient_papers()   sections 3 and 4, per watched ingredient (migration 0039)
  screening_log()                            sections 2 and 6 (migration 0040)
  new_items(), country_look                  section 5 (migration 0032)

The answer for each country (mentioned / nothing found / reads failed / not read) is worked out exactly as the
Ingredients screen works it out (``web/src/features/screen/answers.ts``, ``countryCards`` in
``web/src/features/sources/horizontal.ts``); ``tests/test_report_weekly.py`` holds both to the same cases. A
decision is shown in her words: Concerns us, Doesn't concern us, No decision yet, Reviewed, no decision yet.

Sections, in the PDF (report_templates/weekly.html) and as sheets of the Excel file:
  1 Summary (and the decisions taken)   2 Authorities read   3 Our ingredients by country
  4 NCBI literature   5 Everything new, per authority   6 To check by hand
"""

from __future__ import annotations

import io
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from collectors.report import (CAIRO, CREDIT, PAGE, SATO_LOGO, XLSX_MIME, _env, build_pdf, copyright_line,
                               logo_data_uri, render_footer, xlsx_sheet, xlsx_summary, xlsx_workbook)

log = logging.getLogger("collectors.report")

TITLE = "PHAROS — Weekly screening report"
HERS = "Reference authorities"
OTHERS = "Other authorities"
NOTICE_KINDS = ("safety", "recall")          # the authorities' own notices; spc and literature have sections

# Her two decisions (6 Nov 2026), as the Ingredients screen words them (web/src/features/screen/decision.ts).
DECISION_LABEL = {"new": "No decision yet", "reviewed": "Reviewed, no decision yet",
                  "relevant": "Concerns us", "not_relevant": "Doesn't concern us"}
NO_DECISION = DECISION_LABEL["new"]
DOC_TYPE_LABEL = {"dhpc": "DHPC letter", "safety_alert": "Safety alert", "safety_update": "Safety update",
                  "recall": "Recall", "psusa": "PSUSA outcome", "label_change": "Label change",
                  "signal": "Signal", "newsletter": "Newsletter", "literature": "Literature", "other": "Other"}
KIND_LABEL = {"safety": "Safety notices", "recall": "Recalls", "spc": "Product information (SPC)",
              "literature": "Literature"}
PAGE_KIND = {"database": "Medicines database", "dhpc": "DHPC letters", "safety": "Safety information"}
LANGUAGE = {"en": "English", "de": "German", "fr": "French", "it": "Italian", "es": "Spanish",
            "pt": "Portuguese", "nl": "Dutch", "da": "Danish", "nb": "Norwegian", "no": "Norwegian",
            "sv": "Swedish", "fi": "Finnish", "is": "Icelandic", "ja": "Japanese", "ko": "Korean",
            "ar": "Arabic", "zh": "Chinese", "el": "Greek", "ga": "Irish", "pl": "Polish", "ru": "Russian",
            "tr": "Turkish"}
# The feed rule of new_items(), document_link() and the Sources screen: never shown as a page to open.
FEED_URL = re.compile(r"(\.(xml|json|rss|atom)([?#]|$)|/(rss|feed|atom)(/|[?#]|$)|^https?://api\.)", re.I)
BY_EMAIL = re.compile(r"^By e-mail subscription[:.]?\s*")


# ───────────────────────────── the week ─────────────────────────────

def sunday_of(day: date) -> date:
    """The Sunday that starts the week holding ``day`` (weeks run Sunday to Saturday)."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_label(start: date) -> str:
    """"Sun 26 Oct – Sat 1 Nov 2026"; the first year is written only when the week crosses into a new one."""
    end = start + timedelta(days=6)
    first = f"Sun {start.day} {start:%b}" + (f" {start.year}" if start.year != end.year else "")
    return f"{first} – Sat {end.day} {end:%b %Y}"


@dataclass(frozen=True)
class Week:
    start: date
    name = "Weekly screening report"

    def __post_init__(self) -> None:
        if self.start.weekday() != 6:
            raise ValueError(f"{self.start} is a {self.start:%A}: a week starts on a Sunday "
                             f"({sunday_of(self.start)} starts that week)")

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)

    @property
    def label(self) -> str:
        return week_label(self.start)

    @property
    def slug(self) -> str:
        return self.start.isoformat()

    def bounds_utc(self) -> tuple[datetime, datetime]:
        """Sunday 00:00 to the next Sunday 00:00, Cairo time, as UTC instants: [a, b)."""
        a = datetime.combine(self.start, time(0), CAIRO).astimezone(timezone.utc)
        b = datetime.combine(self.start + timedelta(days=7), time(0), CAIRO).astimezone(timezone.utc)
        return a, b


def week_starting(day: date) -> Week:
    """The week that starts on ``day``; ValueError when it is not a Sunday."""
    return Week(day)


def last_complete_week(now: datetime | None = None) -> Week:
    """The last Sunday-to-Saturday week that has ended in Cairo: on Sunday 8 Nov 2026 at 05:00, 1–7 Nov."""
    today = (now or datetime.now(timezone.utc)).astimezone(CAIRO).date()
    return Week(sunday_of(today) - timedelta(days=7))


# ───────────────────────────── words and dates ─────────────────────────────

def as_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def as_day(v: Any) -> date | None:
    if v is None or isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def day_text(v: Any) -> str:
    """"3 Nov 2026" for a calendar day."""
    d = as_day(v)
    return f"{d.day} {d:%b %Y}" if d else ""


def cairo_time(v: Any) -> str:
    """"5 Nov 2026, 10:12" in Cairo for a stored instant (as on the app's screens)."""
    t = as_dt(v)
    if not t:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(CAIRO)
    return f"{t.day} {t:%b %Y, %H:%M}"


def cairo_day(v: Any) -> date | None:
    t = as_dt(v)
    if not t:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(CAIRO).date()


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def language(code: str | None) -> str:
    return LANGUAGE.get((code or "").lower(), code or "")


def safe_link(url: Any) -> str | None:
    """A web address a person can open, or nothing (never javascript: or a mailbox key)."""
    url = str(url or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def host_of(url: str | None) -> str:
    m = re.match(r"^https?://([^/?#]+)", url or "")
    return m.group(1).removeprefix("www.") if m else ""


def tail_id(url: str | None) -> str:
    """"PMC9" or "1" from an NCBI address."""
    parts = [p for p in (url or "").split("/") if p]
    return parts[-1] if parts else ""


def distinct_words(terms: Iterable[dict]) -> list[dict]:
    """Each matched word once, however many languages list it (as web/src/features/screen/words.ts)."""
    words: dict[str, dict] = {}
    for t in terms or []:
        text = str(t.get("text") or "")
        if not text:
            continue
        w = words.setdefault(text.lower(), {"text": text, "langs": []})
        if t.get("lang") and t["lang"] not in w["langs"]:
            w["langs"].append(t["lang"])
    return list(words.values())


def words_text(terms: Iterable[dict]) -> str:
    """"levofloxacin (English), Fluorchinolone (German), Quinsair (12 languages)"."""
    out = []
    for w in distinct_words(terms):
        n = len(w["langs"])
        out.append(w["text"] if n == 0 else f"{w['text']} ({language(w['langs'][0])})" if n == 1
                   else f"{w['text']} ({n} languages)")
    return ", ".join(out)


# ───────────────────────── the answer for each country (as the Ingredients screen) ─────────────────────────

ANSWER_RANK = {"mentioned": 0, "not_read": 1, "failed": 2, "unread_page": 3, "fine": 4}


def answer_of(mentions: list, runs: int, failed: int, unread_page: bool) -> str:
    """Nothing found is an answer only when the app read the country and could read every page of hers."""
    if mentions:
        return "mentioned"
    if runs == 0:
        return "not_read"
    if failed > 0:
        return "failed"
    if unread_page:
        return "unread_page"
    return "fine"


def to_check_by_hand(answer: str) -> bool:
    return answer in ("not_read", "failed", "unread_page")


def by_newest(mentions: Iterable[dict]) -> list[dict]:
    """Newest first: the day, then when PHAROS first saw it, then the document (as byNewest in answers.ts)."""
    out = sorted(mentions, key=lambda m: str(m.get("document_id")))
    out.sort(key=lambda m: (as_dt(m.get("first_seen_at")) or datetime.min.replace(tzinfo=timezone.utc)),
             reverse=True)
    out.sort(key=lambda m: str(m.get("date") or ""), reverse=True)
    return out


def country_cards(regulators: list[dict], pages: list[dict], sources: list[dict]) -> tuple[list, list]:
    """One card per country (countryCards in horizontal.ts): the countries with pages of hers, A to Z, then every
    other country that has a source."""
    cards: dict[str, dict] = {}
    reg_by_id = {r["id"]: r for r in regulators}
    for r in regulators:
        card = cards.setdefault(r["country_name"], {"country": r["country_name"], "code": r.get("country_code"),
                                                    "regulators": [], "pages": [], "sources": []})
        card["regulators"].append(r)
    for s in sources:
        r = reg_by_id.get(s["regulator_id"])
        if r:
            cards[r["country_name"]]["sources"].append(s)
    for p in pages:
        r = reg_by_id.get(p["regulator_id"])
        if r:
            cards[r["country_name"]]["pages"].append(p)
    for c in cards.values():
        c["regulators"].sort(key=lambda r: r["name"].casefold())
        order = {r["id"]: i for i, r in enumerate(c["regulators"])}
        c["pages"].sort(key=lambda p: (order.get(p["regulator_id"], 0), p.get("sort") or 0))
        c["sources"].sort(key=lambda s: s["id"])
    by_name = sorted(cards.values(), key=lambda c: c["country"].casefold())
    return ([c for c in by_name if c["pages"]],
            [c for c in by_name if not c["pages"] and c["sources"]])


def country_answers(regulators: list[dict]) -> tuple[list[dict], list[dict]]:
    """The screen's answers (countryAnswers in answers.ts) from ingredient_screen()'s regulators: her countries,
    then other authorities; mentions first, then what to check by hand, then nothing found; A to Z within."""
    by_id = {r["id"]: r for r in regulators}
    hers, others = country_cards(regulators, [p for r in regulators for p in r.get("pages") or []],
                                 [s for r in regulators for s in r.get("sources") or []])

    def to_answer(card: dict, mine: bool) -> dict:
        regs = [by_id[r["id"]] for r in card["regulators"] if r["id"] in by_id]
        mentions = by_newest(m for r in regs for m in r.get("mentions") or [])
        runs = sum(int(r.get("runs") or 0) for r in regs)
        ok = sum(int(r.get("ok") or 0) for r in regs)
        failed = sum(int(r.get("failed") or 0) for r in regs)
        unread = any(r.get("unread_page") for r in regs)
        return {"country": card["country"], "code": card["code"], "hers": mine, "regulators": regs,
                "pages": card["pages"], "sources": card["sources"], "mentions": mentions, "runs": runs, "ok": ok,
                "failed": failed, "unread_page": unread,
                "answer": answer_of(mentions, runs, failed, unread)}

    def order(c: dict) -> tuple:
        return ANSWER_RANK[c["answer"]], c["country"].casefold()

    return (sorted((to_answer(c, True) for c in hers), key=order),
            sorted((to_answer(c, False) for c in others), key=order))


def answer_text(c: dict) -> str:
    """The answer in one line, as on the screen, for the week."""
    a = c["answer"]
    if a == "mentioned":
        return f"Mentioned in {plural(len(c['mentions']), 'notice', 'notices')}"
    if a == "not_read":
        return "Not read this week — check it by hand"
    if a == "failed":
        return f"{c['failed']} of {plural(c['runs'], 'read', 'reads')} failed — check it by hand"
    if a == "unread_page":
        return "A page of hers is not read by the app — check it by hand"
    return "Nothing found"


def reads_text(c: dict) -> str:
    if not c["runs"]:
        return "Not read this week"
    read = f"Read {plural(c['runs'], 'time', 'times')} this week"
    return f"{read}, {c['failed']} failed" if c["failed"] else read


def summary_line(countries: list[dict]) -> str:
    """"Mentioned in 2 of 25 countries · 20 nothing found · 3 to check by hand"."""
    mentioned = sum(1 for c in countries if c["answer"] == "mentioned")
    fine = sum(1 for c in countries if c["answer"] == "fine")
    check = sum(1 for c in countries if to_check_by_hand(c["answer"]))
    return (f"Mentioned in {mentioned} of {plural(len(countries), 'country', 'countries')} · "
            f"{fine} nothing found · {check} to check by hand")


def page_status(page: dict, sources: dict[str, dict]) -> dict:
    """Whether the app reads one of her pages: only through sources that exist and are switched on
    (pageStatus in horizontal.ts)."""
    live = [sources[i] for i in page.get("read_by") or [] if i in sources and sources[i].get("enabled")]
    by_email = any(s.get("channel") == "email" for s in live)
    state = "unread" if not live else "partial" if page.get("partial") else "read"
    label = {"unread": "Not read by the app — open it yourself", "partial": "Partly read by the app",
             "read": "Read by the app"}[state]
    if by_email:
        label += ", by e-mail subscription"
    note = (BY_EMAIL.sub("", page.get("note") or "") if by_email else page.get("note") or "").strip()
    return {"state": state, "label": label, "note": note or None}


def source_label(s: dict, pages: list[dict]) -> str:
    """A source in plain words: the name of her page it reads, else what it reads and where."""
    page = next((p for p in pages if s["id"] in (p.get("read_by") or [])), None)
    if page:
        return page["label"]
    where = ""
    for u in (s.get("page_url"), s.get("url")):
        if u and not FEED_URL.search(u):
            where = host_of(u)
            break
    what = KIND_LABEL.get(s.get("kind"), s.get("kind") or "")
    if s.get("channel") == "email":
        what = f"{what} by e-mail"
    return f"{what} · {where}" if where else what


# ───────────────────────────── data ─────────────────────────────

SEARCHES_SQL = r"""
select lower(regexp_replace(btrim(i.inn_en), '\s+', ' ', 'g')) as query, 'name' as kind
  from ingredient i where i.id = %(i)s::uuid
union
select lower(regexp_replace(btrim(ct.term), '\s+', ' ', 'g')), 'class'
  from class_term ct join ingredient_class ic on ic.class_id = ct.class_id
 where ic.ingredient_id = %(i)s::uuid and ct.lang = 'en'
"""


def gather_week(db: Any, week: Week) -> dict:
    """What the report is made from, read from the app's own functions (the database connection is direct, so
    screen_reader() of migration 0040 lets the report read the screen). Nothing filters by run.trigger."""
    a, b = week.bounds_utc()
    days = {"f": week.start, "t": week.end}
    ingredients = db.fetchall(
        "select id::text as id, inn_en from ingredient where active order by lower(inn_en), id")
    screens = []
    for ing in ingredients:
        p = dict(days, i=ing["id"])
        row = db.fetchone("select ingredient_screen(%(i)s::uuid, %(f)s, %(t)s) as screen", p) or {}
        papers = db.fetchall(
            """select document_id::text as document_id, title, lang, journal, day, pubmed_url, pmc_url,
                      by_class, is_backfill, first_seen_at
                 from ingredient_papers(%(i)s::uuid, %(f)s, %(t)s)""", p)
        searches = db.fetchall(SEARCHES_SQL, p)
        screens.append({"screen": row.get("screen") or {}, "papers": papers, "searches": searches})
    return {
        "screens": screens,
        "log": db.fetchall("select * from screening_log(%(f)s, %(t)s)", days),
        "new_items": db.fetchall(
            """select document_id::text as document_id, source_id, regulator_id, regulator_name, country_name,
                      source_kind::text as source_kind, title_orig, lang, link, published_date, first_seen_at,
                      doc_type::text as doc_type, matched, email_id::text as email_id, email_r2_key
                 from new_items(%(a)s, %(b)s)
                order by country_name, first_seen_at desc, document_id""", {"a": a, "b": b}),
        "looks": db.fetchall(
            """select r.country_name, p.full_name as person, max(cl.looked_at) as looked_at, count(*) as looks
                 from country_look cl
                 join person p on p.id = cl.person_id
                 join regulator r on r.id = cl.regulator_id
                where cl.looked_at >= %(a)s and cl.looked_at < %(b)s
                group by r.country_name, p.full_name""", {"a": a, "b": b}),
        "regulators": db.fetchall("select id, name, country_name, country_code, homepage from regulator"),
        "pages": db.fetchall(
            """select id::text as id, regulator_id, kind::text as kind, sort, label, url, read_by, partial, note
                 from regulator_page"""),
        "sources": db.fetchall(
            """select id, regulator_id, kind::text as kind, channel::text as channel, url, page_url, enabled,
                      health::text as health, notes
                 from source"""),
        "decisions": db.fetchall(
            """select re.created_at, re.from_status::text as from_status, re.to_status::text as to_status,
                      re.comment, p.full_name as person, i.title
                 from review_event re
                 join person p on p.id = re.person_id
                 join issue i on i.id = re.issue_id
                where re.created_at >= %(a)s and re.created_at < %(b)s
                order by re.created_at""", {"a": a, "b": b}),
    }


def _authority_cards(raw: dict) -> tuple[list[dict], list[dict]]:
    """The countries as the Sources and Ingredients screens group them: every authority with pages of hers or a
    source of its own notices."""
    notice_regs = {s["regulator_id"] for s in raw["sources"] if s["kind"] not in ("spc", "literature")}
    paged = {p["regulator_id"] for p in raw["pages"]}
    regs = [r for r in raw["regulators"] if r["id"] in notice_regs or r["id"] in paged]
    return country_cards(regs, raw["pages"], raw["sources"])


def _mention(m: dict) -> dict:
    d = m.get("decision") or None
    status = m.get("issue_status")
    return {
        "document_id": m.get("document_id"),
        "day": day_text(m.get("published_date")) if m.get("published_date") else f"Found {day_text(m.get('date'))}",
        "date": str(m.get("date") or ""),
        "title": m.get("title") or "",
        "lang": m.get("lang"),
        "link": safe_link(m.get("link")),
        "by_email": not safe_link(m.get("link")) and bool(m.get("email_id") or m.get("email_r2_key")),
        "authority": m.get("regulator_name") or "",
        "country": m.get("country_name") or "",
        "doc_type": DOC_TYPE_LABEL.get(m.get("doc_type") or "", ""),
        "words": words_text(m.get("terms") or []),
        "by_class": bool(m.get("by_class")),
        "history": bool(m.get("is_backfill")),
        "sections": ", ".join(s for s in (m.get("sections") or []) if isinstance(s, str)),
        "status": status,
        "decision": DECISION_LABEL.get(status or "new", NO_DECISION) if m.get("issue_id") else NO_DECISION,
        "decided_by": (d or {}).get("person") or "",
        "decided_at": cairo_time((d or {}).get("at")),
        "reason": (d or {}).get("comment") or "",
        "awaiting": not m.get("issue_id") or status in (None, "new", "reviewed"),
    }


def _paper(p: dict) -> dict:
    pubmed, pmc = safe_link(p.get("pubmed_url")), safe_link(p.get("pmc_url"))
    return {"document_id": p.get("document_id"), "day": day_text(p.get("day")), "title": p.get("title") or "",
            "lang": p.get("lang"), "journal": p.get("journal") or "", "pubmed": pubmed,
            "pubmed_id": tail_id(pubmed), "pmc": pmc, "pmc_id": tail_id(pmc),
            "by_class": bool(p.get("by_class")), "history": bool(p.get("is_backfill"))}


def assemble(raw: dict, week: Week, made_at: datetime | None = None) -> dict:
    """Everything the PDF and the Excel file show, worked out once so the two files say the same."""
    made_at = made_at or datetime.now(timezone.utc)
    hers, others = _authority_cards(raw)
    log_by_source = {r["source_id"]: r for r in raw["log"]}
    new_by_country: dict[str, list[dict]] = defaultdict(list)
    for it in raw["new_items"]:
        new_by_country[it["country_name"]].append(it)
    looks_by_country: dict[str, list[dict]] = defaultdict(list)
    for lk in sorted(raw["looks"], key=lambda x: as_dt(x["looked_at"]) or made_at, reverse=True):
        looks_by_country[lk["country_name"]].append(
            {"person": lk["person"], "at": cairo_time(lk["looked_at"]), "looks": int(lk.get("looks") or 1)})

    # 2. Authorities read: the reads of their own notices (as the Ingredients screen counts them) and what is new.
    def reads_of(card: dict) -> dict:
        rows = [log_by_source[s["id"]] for s in card["sources"]
                if s["kind"] in NOTICE_KINDS and s["id"] in log_by_source]
        runs = sum(int(r["runs"]) for r in rows)
        return {"country": card["country"], "code": card["code"],
                "authorities": " · ".join(r["name"] for r in card["regulators"]),
                "runs": runs, "ok": sum(int(r["ok_runs"]) for r in rows),
                "failed": sum(int(r["failed_runs"]) for r in rows),
                "new": len(new_by_country.get(card["country"], [])),
                "read": runs > 0}

    def reads_of_kind(kind: str) -> dict:
        rows = [r for r in raw["log"] if r["source_kind"] == kind]
        return {"sources": sum(1 for r in rows if r["enabled"]), "runs": sum(int(r["runs"]) for r in rows),
                "failed": sum(int(r["failed_runs"]) for r in rows),
                "seen": sum(int(r["items_seen"]) for r in rows)}

    authorities = {"hers": [reads_of(c) for c in hers], "others": [reads_of(c) for c in others],
                   "label_watch": reads_of_kind("spc"), "literature": reads_of_kind("literature")}

    # 3 and 4. Our ingredients, each exactly as its Ingredients screen answers for the week.
    ingredients = []
    for entry in raw["screens"]:
        screen = entry["screen"] or {}
        ing = screen.get("ingredient") or {}
        h, o = country_answers(screen.get("regulators") or [])
        countries = []
        for group, cs in ((HERS, h), (OTHERS, o)):
            for c in cs:
                countries.append({"group": group, "country": c["country"], "answer": c["answer"],
                                  "answer_text": answer_text(c), "reads_text": reads_text(c),
                                  "check": to_check_by_hand(c["answer"]),
                                  "several": len(c["regulators"]) > 1,
                                  "mentions": [_mention(m) for m in c["mentions"]]})
        lit = screen.get("literature") or {}
        counts = {q.get("query"): q for q in lit.get("by_query") or []}
        searches = sorted(entry["searches"], key=lambda s: (s["kind"] != "name", s["query"]))
        ingredients.append({
            "id": ing.get("id"),
            "name": ing.get("inn_en") or "",
            "atc": ing.get("atc_code") or "",
            "classes": ", ".join(c.get("name_en") or "" for c in ing.get("classes") or []),
            "summary": summary_line(h + o),
            "countries": countries,
            "label_changes": [_mention(m) for m in screen.get("label_changes") or []],
            "literature": {
                "papers": int(lit.get("papers") or 0), "by_name": int(lit.get("by_name") or 0),
                "by_class": int(lit.get("by_class") or 0), "pubmed": int(lit.get("pubmed") or 0),
                "pmc": int(lit.get("pmc") or 0),
                "searches": [{"query": s["query"], "kind": "name" if s["kind"] == "name" else "class word",
                              "pubmed": int((counts.get(s["query"]) or {}).get("pubmed") or 0),
                              "pmc": int((counts.get(s["query"]) or {}).get("pmc") or 0)} for s in searches],
                "list": [_paper(p) for p in entry["papers"]],
            },
        })

    # 5. Everything new per authority, with who looked at the country and when.
    def item(it: dict) -> dict:
        pub = it.get("published_date")
        link = safe_link(it.get("link"))
        return {"day": day_text(pub) if pub else f"Found {day_text(cairo_day(it.get('first_seen_at')))}",
                "title": it.get("title_orig") or "", "lang": it.get("lang"), "link": link,
                "by_email": not link and bool(it.get("email_id") or it.get("email_r2_key")),
                "authority": it.get("regulator_name") or "", "kind": KIND_LABEL.get(it.get("source_kind"), ""),
                "doc_type": DOC_TYPE_LABEL.get(it.get("doc_type") or "", ""), "matched": bool(it.get("matched")),
                "sort": (str(pub or cairo_day(it.get("first_seen_at")) or ""), as_dt(it.get("first_seen_at")))}

    new = []
    for group, cards in ((HERS, hers), (OTHERS, others)):
        for c in cards:
            items = [item(it) for it in new_by_country.get(c["country"], [])]
            items.sort(key=lambda x: x["sort"][1] or made_at, reverse=True)
            items.sort(key=lambda x: x["sort"][0], reverse=True)
            new.append({"group": group, "country": c["country"],
                        "authorities": " · ".join(r["name"] for r in c["regulators"]),
                        "items": items, "looks": looks_by_country.get(c["country"], [])})

    # 6. To check by hand: her pages the app does not read (or reads only in part), and the sources whose reads
    # failed or that were not read this week.
    sources_by_id = {s["id"]: s for s in raw["sources"]}
    reg_by_id = {r["id"]: r for r in raw["regulators"]}
    pages = []
    for c in hers:
        for p in c["pages"]:
            st = page_status(p, sources_by_id)
            if st["state"] != "read":
                pages.append({"country": c["country"], "label": p["label"], "kind": PAGE_KIND.get(p["kind"], ""),
                              "url": safe_link(p["url"]), "status": st["label"], "note": st["note"] or "",
                              "state": st["state"]})
    all_pages = raw["pages"]
    failed, unread = [], []
    for r in sorted(raw["log"], key=lambda r: (str(r["country"]).casefold(), r["source_id"])):
        s = sources_by_id.get(r["source_id"]) or {"id": r["source_id"], "kind": r["source_kind"]}
        row = {"country": r["country"], "authority": r["regulator"],
               "source": source_label(s, [p for p in all_pages if p["regulator_id"] == r["regulator_id"]]),
               "kind": KIND_LABEL.get(r["source_kind"], ""), "runs": int(r["runs"]),
               "failed": int(r["failed_runs"]), "why": (r.get("last_failure") or "")[:300],
               "page": safe_link(s.get("page_url")) or (safe_link(s.get("url"))
                                                         if not FEED_URL.search(s.get("url") or "") else None)
                       or safe_link((reg_by_id.get(r["regulator_id"]) or {}).get("homepage"))}
        if int(r["failed_runs"]) > 0:
            failed.append(row)
        elif r["enabled"] and int(r["runs"]) == 0:
            unread.append(row)

    decisions = [{"at": cairo_time(d["created_at"]), "title": d["title"] or "",
                  "decision": DECISION_LABEL.get(d["to_status"], d["to_status"]),
                  "before": DECISION_LABEL.get(d["from_status"], d["from_status"]),
                  "person": d["person"], "reason": d["comment"] or ""} for d in raw["decisions"]]

    # 1. Summary
    found = {m["document_id"]: m for i in ingredients for c in i["countries"] for m in c["mentions"]}
    labels = {m["document_id"] for i in ingredients for m in i["label_changes"]}
    papers = {p["document_id"] for i in ingredients for p in i["literature"]["list"]}
    to_check_answers = sum(1 for i in ingredients for c in i["countries"] if c["check"])
    hers_read = sum(1 for r in authorities["hers"] if r["read"])
    others_read = sum(1 for r in authorities["others"] if r["read"])
    runs = sum(r["runs"] for r in authorities["hers"] + authorities["others"])
    runs_failed = sum(r["failed"] for r in authorities["hers"] + authorities["others"])
    summary = [
        ("Report", TITLE),
        ("Week (Cairo time)", week.label),
        ("Made (Cairo)", cairo_time(made_at)),
        ("Reference countries read", f"{hers_read} of {len(authorities['hers'])}"),
        ("Other authorities read", f"{others_read} of {len(authorities['others'])}"),
        ("Reads of the authorities' notices", runs),
        ("Reads that failed", runs_failed),
        ("New items published", len(raw["new_items"])),
        ("Watched ingredients", len(ingredients)),
        ("Notices naming our ingredients or their class", len(found)),
        ("Of them, history (never alerted)", sum(1 for m in found.values() if m["history"])),
        ("Of them, no decision yet", sum(1 for m in found.values() if m["awaiting"])),
        ("Label changes", len(labels)),
        ("Papers in PubMed and PubMed Central", len(papers)),
        ("Decisions taken this week", len(decisions)),
        ("Country answers to check by hand", to_check_answers),
        ("Pages to check by hand", len(pages)),
        ("Sources whose reads failed", len(failed)),
        ("Sources not read this week", len(unread)),
    ]
    figures = [("Reference countries read", f"{hers_read} / {len(authorities['hers'])}"),
               ("New items", len(raw["new_items"])),
               ("Notices naming our ingredients", len(found)),
               ("To check by hand", len(pages) + len(failed) + len(unread))]
    return {"week": week, "made_at": made_at, "summary": summary, "figures": figures, "decisions": decisions,
            "authorities": authorities, "ingredients": ingredients, "new": new,
            "check": {"pages": pages, "failed": failed, "unread": unread}}


# ───────────────────────────── Excel ─────────────────────────────

SHEETS = ("Summary", "Decisions", "Authorities read", "Ingredients by country", "NCBI searches", "NCBI papers",
          "Everything new", "To check by hand")


def build_weekly_xlsx(data: dict) -> bytes:
    week: Week = data["week"]
    wb = xlsx_workbook(f"{TITLE}, {week.label}")
    xlsx_summary(wb.active, data["summary"])

    def yes(v: bool) -> str:
        return "yes" if v else ""

    xlsx_sheet(wb, "Decisions",
               ["When (Cairo)", "Notice (original title)", "Decision", "Before", "By", "Reason"],
               [[d["at"], d["title"], d["decision"], d["before"], d["person"], d["reason"]]
                for d in data["decisions"]],
               [18, 60, 22, 22, 22, 50])
    a = data["authorities"]
    xlsx_sheet(wb, "Authorities read",
               ["Group", "Country", "Authorities", "Reads", "OK", "Failed", "New items"],
               [[g, r["country"], r["authorities"], r["runs"], r["ok"], r["failed"], r["new"]]
                for g, rows in ((HERS, a["hers"]), (OTHERS, a["others"])) for r in rows]
               + [["Label watch", "", "Product information of our ingredients", a["label_watch"]["runs"],
                   a["label_watch"]["runs"] - a["label_watch"]["failed"], a["label_watch"]["failed"], ""],
                  ["NCBI literature", "", "PubMed and PubMed Central", a["literature"]["runs"],
                   a["literature"]["runs"] - a["literature"]["failed"], a["literature"]["failed"], ""]],
               [20, 22, 50, 8, 8, 8, 10])
    rows = []
    for i in data["ingredients"]:
        for c in i["countries"]:
            base = [i["name"], c["group"], c["country"], c["answer_text"], c["reads_text"]]
            if not c["mentions"]:
                rows.append(base + [""] * 13)
            for m in c["mentions"]:
                rows.append(base + [m["day"], m["title"], language(m["lang"]), m["link"] or (
                    "By e-mail: open it in PHAROS" if m["by_email"] else ""), m["authority"], m["doc_type"],
                    m["words"], yes(m["by_class"]), yes(m["history"]), m["decision"], m["decided_by"],
                    m["decided_at"], m["reason"]])
        for m in i["label_changes"]:
            rows.append([i["name"], "Label changes", m["country"], "", "", m["day"], m["title"],
                         language(m["lang"]), m["link"] or "", m["authority"], m["doc_type"],
                         m["sections"] and f"Sections changed: {m['sections']}" or m["words"],
                         yes(m["by_class"]), yes(m["history"]), m["decision"], m["decided_by"], m["decided_at"],
                         m["reason"]])
    xlsx_sheet(wb, "Ingredients by country",
               ["Ingredient", "Group", "Country", "Answer", "Reads", "Date", "Notice (original title)",
                "Language", "Link", "Authority", "Type", "Words matched", "By class", "History", "Decision",
                "Decided by", "Decided (Cairo)", "Reason"],
               rows, [18, 20, 18, 34, 22, 14, 60, 12, 50, 26, 16, 34, 9, 9, 22, 22, 18, 44], links=True)
    xlsx_sheet(wb, "NCBI searches",
               ["Ingredient", "Search", "Searched as", "PubMed", "PubMed Central"],
               [[i["name"], s["query"], s["kind"], s["pubmed"], s["pmc"]]
                for i in data["ingredients"] for s in i["literature"]["searches"]],
               [18, 36, 14, 10, 16])
    xlsx_sheet(wb, "NCBI papers",
               ["Ingredient", "Date", "Title", "Journal", "PubMed", "PubMed Central", "By class", "History"],
               [[i["name"], p["day"], p["title"], p["journal"], p["pubmed"] or "", p["pmc"] or "",
                 yes(p["by_class"]), yes(p["history"])]
                for i in data["ingredients"] for p in i["literature"]["list"]],
               [18, 14, 70, 30, 40, 46, 9, 9], links=True)
    xlsx_sheet(wb, "Everything new",
               ["Group", "Country", "Authority", "Date", "Title (original)", "Language", "Link", "Kind", "Type",
                "Matched the watchlist", "Looked at this week by"],
               [[n["group"], n["country"], it["authority"], it["day"], it["title"], language(it["lang"]),
                 it["link"] or ("By e-mail: open it in PHAROS" if it["by_email"] else ""), it["kind"],
                 it["doc_type"], yes(it["matched"]), _looks_text(n["looks"])]
                for n in data["new"] for it in n["items"]],
               [20, 18, 26, 14, 64, 12, 50, 16, 16, 12, 40], links=True)
    ch = data["check"]
    xlsx_sheet(wb, "To check by hand",
               ["What", "Country", "Authority", "Page or source", "Kind", "Address", "Why"],
               [["Her page, " + p["status"].lower(), p["country"], "", p["label"], p["kind"], p["url"] or "",
                 p["note"]] for p in ch["pages"]]
               + [["Reads failed", r["country"], r["authority"], r["source"], r["kind"], r["page"] or "",
                   f"{r['failed']} of {plural(r['runs'], 'read', 'reads')} failed. {r['why']}".strip()]
                  for r in ch["failed"]]
               + [["Not read this week", r["country"], r["authority"], r["source"], r["kind"], r["page"] or "",
                   "No read this week"] for r in ch["unread"]],
               [34, 18, 26, 36, 18, 50, 60], links=True)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _looks_text(looks: list[dict]) -> str:
    return "; ".join(f"{lk['person']}, {lk['at']}" for lk in looks)


# ───────────────────────────── PDF ─────────────────────────────

def render_weekly_html(data: dict) -> str:
    env = _env()
    env.filters["language"] = language
    return env.get_template("weekly.html").render(
        title=TITLE, week=data["week"], page=PAGE, data=data, hers=HERS, others=OTHERS,
        looks_text=_looks_text, logo_src=logo_data_uri(), sato_src=logo_data_uri(SATO_LOGO), credit=CREDIT,
        copyright=copyright_line())


# ───────────────────────────── made, stored, sent ─────────────────────────────

def file_stem(week: Week) -> str:
    return f"PHAROS-weekly-{week.slug}"


def run_address() -> str | None:
    """The GitHub Actions run that makes the report, when it is one."""
    server, repo, run = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{server}/{repo}/actions/runs/{run}" if server and repo and run else None


def make_weekly_report(db: Any, store: Any, week: Week, *, dry_run: bool = False) -> dict:
    from collectors.alerts import Notifier
    from collectors.core.archive import Archive

    data = assemble(gather_week(db, week), week)
    xlsx = build_weekly_xlsx(data)
    pdf = build_pdf(render_weekly_html(data), render_footer(week))
    archive = Archive()
    stem = file_stem(week)
    base = f"reports/weekly/{week.slug}/{stem}"
    # A week made again never overwrites (bucket lock): it is stored as -r2, -r3 …; the row keeps the latest,
    # and the audit log the earlier ones.
    xlsx_sha, xlsx_key = archive.put_named(f"{base}.xlsx", xlsx, XLSX_MIME, revise=True)
    pdf_sha, pdf_key = archive.put_named(f"{base}.pdf", pdf, "application/pdf", revise=True)
    db.execute(
        """insert into weekly_report (week_start, week_end, xlsx_r2_key, xlsx_sha256, pdf_r2_key, pdf_sha256,
                                      git_sha, made_by_run)
           values (%(s)s, %(e)s, %(xk)s, %(xs)s, %(pk)s, %(ps)s, %(g)s, %(r)s)
           on conflict (week_start) do update set xlsx_r2_key = excluded.xlsx_r2_key,
             xlsx_sha256 = excluded.xlsx_sha256, pdf_r2_key = excluded.pdf_r2_key,
             pdf_sha256 = excluded.pdf_sha256, git_sha = excluded.git_sha, made_by_run = excluded.made_by_run,
             made_at = now()""",
        {"s": week.start, "e": week.end, "xk": xlsx_key, "xs": xlsx_sha, "pk": pdf_key, "ps": pdf_sha,
         "g": os.environ.get("GIT_SHA") or os.environ.get("GITHUB_SHA"), "r": run_address()})
    out_dir = Path(os.environ.get("REPORT_DIR", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stem}.xlsx").write_bytes(xlsx)
    (out_dir / f"{stem}.pdf").write_bytes(pdf)
    notifier = Notifier(store, store.settings(), dry_run=dry_run, archive=archive)
    notifier.admin_document(f"{stem}.pdf", pdf, f"{TITLE}, {week.label}")
    return {"week": week.slug, "xlsx_sha256": xlsx_sha, "pdf_sha256": pdf_sha}


__all__ = ["Week", "week_starting", "last_complete_week", "gather_week", "assemble", "build_weekly_xlsx",
           "render_weekly_html", "make_weekly_report", "country_answers", "answer_text"]
