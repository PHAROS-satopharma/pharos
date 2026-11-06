"""Suggest the codes of one case (migration 0061): MeSH for each reaction, indication and medical-history
condition, RxNorm for each product. Nothing here decides: the suggestions go to ``safety_case.coding`` and a
reviewer chooses each code into the form.

For each set of words, best first:
  memory     the code people chose for the same words in confirmed cases (``coding_memory``);
  reader     the reader's choice among MeSH's closest descriptors: Claude first names the medical concept in
             standard English (from words in any language), PHAROS looks those names up in MeSH, and Claude then
             picks the most specific descriptor among what MeSH returned, with one sentence of reason. It can only
             choose a descriptor PHAROS found: it never writes a code;
  search     MeSH's closest names to the words themselves (all there is when the reader is not set up).
Products: what the team chose before, the watched ingredient the product names, then RxNorm (``drugs``).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from collectors.coding import drugs
from collectors.coding.norm import norm
from collectors.core.db import jsonb

log = logging.getLogger("collectors.coding.coder")

MODEL = "claude-opus-5-5"
MAX_TOKENS = 8000
PER_ITEM = 5

SYSTEM = (
    "You help a pharmacovigilance team code adverse event reports with MeSH, the National Library of Medicine's "
    "Medical Subject Headings. You never invent a code. You either name medical concepts in standard English, or "
    "choose among candidate MeSH descriptors you are given. Reports can be in any language, Arabic included.")

TERMS_ASK = """Each item below is a set of words from one case report: a reaction the patient had, or the
indication (why the patient took a product). For each item, give one to three standard English medical terms that
name the condition the words describe, as MeSH names conditions (for example "Exanthema", "Chemical and Drug
Induced Liver Injury", "Hypertension"), the most specific first.

Then split the patient's medical history (it may be empty) into its separate conditions, each in the words of the
report, and give one to three terms for each. Leave out what is not a condition (a smoking habit is a condition;
"no allergies" is not).

Items:
{items}

Medical history:
{history}"""

CHOOSE_ASK = """For each item, choose the one candidate descriptor that names what the report describes most
specifically and most exactly: a sign named by the reporter is coded as that sign, not as a disease the reporter
did not name. Give its ui as "choice", or "" when no candidate fits. In "also", give up to two other candidates'
ui that a reviewer might prefer. In "reason", one short plain sentence a pharmacist can check.

{items}"""


def _array(item: dict) -> dict:
    return {"type": "array", "items": item}


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_STR = {"type": "string"}
TERMS_SCHEMA = _obj({
    "items": _array(_obj({"id": _STR, "terms": _array(_STR)})),
    "history": _array(_obj({"condition": _STR, "terms": _array(_STR)})),
})
CHOICE_SCHEMA = _obj({"items": _array(_obj({"id": _STR, "choice": _STR, "also": _array(_STR), "reason": _STR}))})


class Reader:
    """The two questions put to Claude. Raises on any failure: the coder then falls back to the search."""

    def __init__(self, client: Any = None) -> None:
        from collectors.core import claude

        self.client = client or claude.client()
        self.model = MODEL

    def _ask(self, text: str, schema: dict) -> dict:
        with self.client.messages.stream(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        ) as stream:
            message = stream.get_final_message()
        if message.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"the reader stopped ({message.stop_reason})")
        self.model = getattr(message, "model", MODEL)
        return json.loads(next(b.text for b in message.content if b.type == "text"))

    def terms(self, items: list[dict], history: str) -> dict:
        listed = json.dumps([{"id": i["id"], "words": i["text"], "is": i["kind"]} for i in items], ensure_ascii=False)
        return self._ask(TERMS_ASK.format(items=listed, history=history or "(none)"), TERMS_SCHEMA)

    def choose(self, items: list[dict]) -> dict:
        listed = json.dumps([{"id": i["id"], "words": i["text"], "is": i["kind"],
                              "candidates": [{"ui": c["ui"], "name": c["name"], "matched_name": c["term"],
                                              "body_system": c["categories"]} for c in i["candidates"]]}
                             for i in items], ensure_ascii=False)
        return self._ask(CHOOSE_ASK.format(items=listed), CHOICE_SCHEMA)


def search(db: Any, text: str, n: int = 8) -> list[dict]:
    if len(norm(text)) < 3:
        return []
    return db.fetchall("select ui, name, term, trees, categories, score from mesh_search(%s, %s)", (text, n))


def remembered(db: Any, kind: str, text: str) -> list[dict]:
    if not norm(text):
        return []
    return db.fetchall("""select code, label, cases from coding_memory
                           where kind = %s and norm = coding_norm(%s) order by cases desc, code limit 2""",
                       (kind, text))


def _descriptors(db: Any, uis: list[str]) -> dict[str, dict]:
    if not uis:
        return {}
    rows = db.fetchall("select ui, name, mesh_category(trees) as categories from mesh_descriptor where ui = any(%s)",
                       (list(uis),))
    return {r["ui"]: r for r in rows}


def items_of(form: dict) -> list[dict]:
    """The words to code with MeSH: each reaction (its English, else as written) and each product's indication."""
    out = []
    for i, r in enumerate(form.get("reactions") or []):
        text = (r.get("english") or r.get("verbatim") or "").strip()
        if text:
            out.append({"id": f"r{i}", "kind": "reaction", "index": i, "text": text,
                        "also_said": (r.get("verbatim") or "").strip()})
    for i, p in enumerate(form.get("products") or []):
        text = (p.get("indication") or "").strip()
        if text:
            out.append({"id": f"i{i}", "kind": "indication", "index": i, "text": text, "also_said": ""})
    return out


def _suggest_mesh(db: Any, item: dict, pick: dict | None, kind: str) -> list[dict]:
    """The suggestions for one set of words, best first, at most PER_ITEM."""
    out: list[dict] = []
    memory = []
    for words in {item["text"], item.get("also_said") or ""} - {""}:
        memory += remembered(db, kind, words)
    known = _descriptors(db, [m["code"] for m in memory] + ([pick["choice"], *pick["also"]] if pick else []))
    for m in memory:
        d = known.get(m["code"])
        if d:
            out.append({"ui": d["ui"], "name": d["name"], "categories": d["categories"], "from": "memory",
                        "reason": f"Chosen for these words in {m['cases']} confirmed case(s)."})
    if pick:
        for k, ui in enumerate([pick["choice"], *pick["also"]]):
            d = known.get(ui)
            if d:
                out.append({"ui": d["ui"], "name": d["name"], "categories": d["categories"], "from": "reader",
                            "reason": pick["reason"] if k == 0 else "Another fitting descriptor."})
    for c in item.get("candidates") or search(db, item["text"]):
        out.append({"ui": c["ui"], "name": c["name"], "categories": c["categories"], "from": "search",
                    "reason": f"MeSH's closest name: “{c['term']}”."})
    seen: set[str] = set()
    unique = []
    for s in out:
        if s["ui"] not in seen:
            seen.add(s["ui"])
            unique.append(s)
    return unique[:PER_ITEM]


def _candidates(db: Any, words: list[str]) -> list[dict]:
    """MeSH's closest descriptors to any of ``words``, best score first, at most 15."""
    best: dict[str, dict] = {}
    for w in words:
        for c in search(db, w):
            if c["ui"] not in best or c["score"] > best[c["ui"]]["score"]:
                best[c["ui"]] = c
    return sorted(best.values(), key=lambda c: -c["score"])[:15]


def code_form(db: Any, form: dict, *, reader: Reader | None = None,
              rx: drugs.RxNav | None = None) -> dict:
    """The suggestions for one case form (the value of ``safety_case.coding``)."""
    items = items_of(form)
    history = ((form.get("patient") or {}).get("medical_history") or "").strip()
    named: dict = {"items": [], "history": []}
    note = None
    if reader is not None and (items or history):
        try:
            named = reader.terms(items, history)
        except Exception as exc:  # noqa: BLE001 - the search alone still suggests
            note = f"The reader could not be asked ({type(exc).__name__}); the suggestions are MeSH's closest names."
            reader = None
    terms_of = {t["id"]: t["terms"] for t in named.get("items") or []}
    conditions = [{"id": f"h{k}", "kind": "history", "text": h["condition"].strip(), "also_said": "",
                   "terms": h["terms"]} for k, h in enumerate(named.get("history") or []) if h["condition"].strip()]
    if not conditions and history:
        conditions = [{"id": f"h{k}", "kind": "history", "text": part.strip(), "also_said": "", "terms": []}
                      for k, part in enumerate(history.replace("\n", ";").split(";")) if part.strip()]
    every = items + conditions
    for it in every:
        it["candidates"] = _candidates(db, [it["text"], it["also_said"], *terms_of.get(it["id"], []),
                                            *it.get("terms", [])])
    picks: dict[str, dict] = {}
    if reader is not None and any(it["candidates"] for it in every):
        try:
            asked = [it for it in every if it["candidates"]]
            for p in reader.choose(asked).get("items") or []:
                allowed = {c["ui"] for it in asked if it["id"] == p["id"] for c in it["candidates"]}
                also = [u for u in p["also"] if u in allowed and u != p["choice"]][:2]
                if p["choice"] in allowed:
                    picks[p["id"]] = {"choice": p["choice"], "also": also, "reason": p["reason"].strip()[:300]}
                elif also:   # its choice was not one of MeSH's: only its alternatives stand, without its reason
                    picks[p["id"]] = {"choice": also[0], "also": also[1:], "reason": "Another fitting descriptor."}
        except Exception as exc:  # noqa: BLE001
            note = f"The reader could not choose ({type(exc).__name__}); the suggestions are MeSH's closest names."

    def entry(it: dict) -> dict:
        pick = picks.get(it["id"])
        return {"kind": it["kind"], "index": it.get("index"), "text": it["text"], "norm": norm(it["text"]),
                "suggestions": _suggest_mesh(db, it, pick, "indication" if it["kind"] == "indication"
                                             else "reaction")}

    ingredients = drugs.watchlist(db)
    products = []
    for i, p in enumerate(form.get("products") or []):
        name, active = (p.get("name") or "").strip(), (p.get("active_ingredient") or "").strip()
        if not (name or active):
            continue
        memory = remembered(db, "product", name) + remembered(db, "product", active)
        products.append({"index": i, "text": name or active, "norm": norm(f"{name} {active}"),
                         "suggestions": drugs.suggest(p, ingredients, rx, memory)})
    dictionary = db.fetchone("select version from coding_dictionary where name = 'mesh'")
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mesh": dictionary["version"] if dictionary else None,
        "reader": reader.model if reader is not None else None,
        "note": note if dictionary else "MeSH is not loaded yet: only the products are suggested.",
        "items": [entry(it) for it in items],
        "history": [entry(it) for it in conditions],
        "products": products,
    }


WAITING_SQL = """
select id, ref, data from safety_case
 where (%(case)s::uuid is null or id = %(case)s::uuid)
   and status in ('to_confirm','confirmed','sent')
   and (coding_status = 'queued' or coding_status is null
        or (coding_status = 'done' and read_at is not null and read_at > coded_at))
 order by created_at
 limit %(limit)s"""


def code_waiting(db: Any, *, case_id: str | None = None, limit: int = 20,
                 make_reader: Callable[[], Reader | None] | None = None,
                 rx: drugs.RxNav | None = None) -> dict[str, int]:
    """Code each case asked for (or read since it was last coded); counts per outcome."""
    cases = db.fetchall(WAITING_SQL, {"case": case_id, "limit": limit})
    if not cases:
        return {}
    reader = make_reader() if make_reader else None
    rx = rx or drugs.RxNav()
    counts: dict[str, int] = {}
    for c in cases:
        try:
            coding = code_form(db, c["data"] or {}, reader=reader, rx=rx)
            db.execute("""update safety_case set coding = %(c)s, coding_status = 'done', coding_error = null,
                                 coded_at = now()
                           where id = %(id)s""", {"c": jsonb(coding), "id": c["id"]})
            outcome = "coded"
            log.info("case %s coded: %d item(s), %d condition(s), %d product(s)", c["ref"], len(coding["items"]),
                     len(coding["history"]), len(coding["products"]))
        except Exception as exc:  # noqa: BLE001 - one case never stops the others
            log.exception("case %s: coding failed", c["ref"])
            db.execute("""update safety_case set coding_status = 'failed', coding_error = %(e)s, coded_at = now()
                           where id = %(id)s""", {"e": f"Coding failed: {type(exc).__name__}", "id": c["id"]})
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def default_reader() -> Reader | None:
    from collectors.core import claude

    if not claude.configured():
        log.info("%s: codes come from MeSH's closest names", claude.MISSING)
        return None
    return Reader()
