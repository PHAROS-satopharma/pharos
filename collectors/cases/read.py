"""Read a case's source document and fill in its form (migration 0059).

One case at a time: the case is claimed (queued → reading, one more attempt), its original is read back from the
archive and checked against its SHA-256, and the reader (``claude-opus-5-5``, structured output in the shape of
``schema.CASE_SCHEMA``) fills in the form. What it returned is kept unchanged in ``extracted``; the form the team
starts from goes to ``data``, the case waits for a reviewer (``to_confirm``), and the step is logged with no person
(PHAROS itself). Seriousness is never set here: the reader's view stays in ``extracted`` and the reviewer decides.

A passing failure (the API overloaded, the network) puts the case back in the queue for the next run; after
``MAX_ATTEMPTS`` tries, or for a document the reader cannot take, the case is marked failed with the reason, which
the reviewer sees with a "Read again" button. A case left in ``reading`` by a run that died is taken again after
``STUCK_MINUTES``.

Sign-in: federation in the workflows, or ``ANTHROPIC_API_KEY`` by hand (``collectors.core.claude``). Only the
document goes to the API; the ingredient names the company watches go with it so the reader can tell the suspect
product.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from collectors.cases import content, schema
from collectors.core.archive import Archive, sha256_hex
from collectors.core.db import jsonb

log = logging.getLogger("collectors.cases.read")

MODEL = "claude-opus-5-5"
MAX_TOKENS = 32000
MAX_ATTEMPTS = 3
STUCK_MINUTES = 30


class ReadFailed(Exception):
    """The reader could not fill in the form. ``passing`` failures are tried again on the next run."""

    def __init__(self, message: str, *, passing: bool = False) -> None:
        super().__init__(message)
        self.passing = passing


CLAIM_SQL = f"""
update safety_case set status = 'reading', read_attempts = read_attempts + 1, updated_at = clock_timestamp()
 where id = (select id from safety_case
              where (%(case)s::uuid is null or id = %(case)s::uuid)
                and not (id = any(%(done)s::uuid[]))
                and (status = 'queued'
                     or (status = 'reading' and updated_at < now() - interval '{STUCK_MINUTES} minutes'))
                and read_attempts < {MAX_ATTEMPTS}
              order by created_at
              limit 1
              for update skip locked)
returning *"""


def claim(db: Any, case_id: str | None = None, done: list[str] | None = None) -> dict | None:
    """Take one waiting case (``case_id``, or the oldest not in ``done``), or None when there is none."""
    return db.fetchone(CLAIM_SQL, {"case": case_id, "done": done or []})


def waiting(db: Any) -> int:
    row = db.fetchone(
        f"""select count(*) as n from safety_case
             where read_attempts < {MAX_ATTEMPTS}
               and (status = 'queued'
                    or (status = 'reading' and updated_at < now() - interval '{STUCK_MINUTES} minutes'))""")
    return int(row["n"]) if row else 0


def watched_ingredients(db: Any) -> list[dict]:
    """The active ingredients with every name they are known by (lower case), for the prompt and the match."""
    rows = db.fetchall(
        """select i.id, i.inn_en,
                  coalesce(array_agg(distinct lower(t.term)) filter (where t.term is not null), '{}') as terms
             from ingredient i
             left join ingredient_term t on t.ingredient_id = i.id
            where i.active
            group by i.id, i.inn_en
            order by i.inn_en""")
    return [{"id": str(r["id"]), "inn_en": r["inn_en"],
             "names": sorted({r["inn_en"].lower(), *[t for t in r["terms"] if t]})} for r in rows]


def _words(text: str) -> str:
    return " " + re.sub(r"[^\w]+", " ", (text or "").lower()) + " "


def guess_ingredient(form: dict, ingredients: list[dict]) -> str | None:
    """The one watched ingredient named by the suspect products (by INN or any known name); None when there is
    none or more than one: then the reviewer chooses."""
    said = "".join(_words(f"{p.get('name') or ''} {p.get('active_ingredient') or ''}")
                   for p in form.get("products") or [] if p.get("role") == "suspect")
    hits = {i["id"] for i in ingredients for n in i["names"] if n and _words(n).strip() and _words(n) in said}
    return hits.pop() if len(hits) == 1 else None


def call_reader(blocks: list[dict], ingredients: list[dict], client: Any = None) -> tuple[dict, str]:
    """The reader's answer (parsed JSON) and the model that gave it."""
    import anthropic

    from collectors.core import claude

    client = client or claude.client()
    names = ", ".join(i["inn_en"] for i in ingredients) or "(none listed)"
    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=schema.SYSTEM,
            messages=[{"role": "user",
                       "content": [*blocks, {"type": "text", "text": schema.INSTRUCTION.format(ingredients=names)}]}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": schema.CASE_SCHEMA}},
        ) as stream:
            message = stream.get_final_message()
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
        raise ReadFailed(f"The reader could not be reached ({type(exc).__name__}).", passing=True) from exc
    except anthropic.WorkloadIdentityError as exc:
        raise ReadFailed(f"PHAROS could not sign in to the reader: {str(exc)[:300]}", passing=True) from exc
    except anthropic.APIStatusError as exc:
        raise ReadFailed(f"The reader refused the request (HTTP {exc.status_code}): {str(exc)[:300]}") from exc
    if message.stop_reason == "refusal":
        raise ReadFailed("The reader declined this document. Fill in the form by hand.")
    if message.stop_reason == "max_tokens":
        raise ReadFailed("The document is too long to read in one go. Fill in the form by hand.")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        reading = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReadFailed("The reader's answer was not complete.", passing=True) from exc
    return reading, getattr(message, "model", MODEL)


def source_bytes(case: dict, archive: Archive) -> bytes:
    if not case.get("r2_key"):
        raise ReadFailed("The case has no document yet.", passing=case.get("origin") == "paper")
    data = archive.get(case["r2_key"])
    if data is None:
        raise ReadFailed("The document could not be read back from the archive.", passing=True)
    if case.get("sha256") and sha256_hex(data) != case["sha256"]:
        raise ReadFailed("The archived document does not match its SHA-256. Upload it again.")
    return data


def _fail(db: Any, case: dict, exc: ReadFailed) -> str:
    again = exc.passing and case["read_attempts"] < MAX_ATTEMPTS
    status = "queued" if again else "failed"
    with db.transaction():
        db.execute("""update safety_case set status = %(s)s, read_error = %(e)s, updated_at = clock_timestamp()
                       where id = %(id)s""", {"s": status, "e": str(exc)[:1000], "id": case["id"]})
        if not again:
            db.execute("""insert into case_event (case_id, step, from_status, to_status, comment)
                          values (%(id)s, 'read_failed', 'reading', 'failed', %(e)s)""",
                       {"id": case["id"], "e": str(exc)[:1000]})
    log.warning("case %s: %s (%s)", case["ref"], exc, "will try again" if again else "failed")
    return status


def store_reading(db: Any, case: dict, reading: dict, model: str, ingredients: list[dict]) -> None:
    form = schema.form_from_reading(reading)
    ingredient = case.get("ingredient_id") or guess_ingredient(form, ingredients)
    missing = schema.missing(form)
    note = "Read" + (f"; still missing: {', '.join(missing)}" if missing else "; the four minimum criteria are there")
    if reading.get("is_case") is False:
        note += "; the reader found no individual case in the document"
    with db.transaction():
        db.execute(
            """update safety_case set status = 'to_confirm', extracted = %(x)s, data = %(d)s,
                      ingredient_id = %(ing)s, reader_model = %(m)s, read_at = now(), read_error = null,
                      updated_at = clock_timestamp()
                where id = %(id)s and status = 'reading'""",
            {"x": jsonb(reading), "d": jsonb(form), "ing": ingredient, "m": model, "id": case["id"]})
        db.execute("""insert into case_event (case_id, step, from_status, to_status, comment, data)
                      values (%(id)s, 'read', 'reading', 'to_confirm', %(c)s, %(d)s)""",
                   {"id": case["id"], "c": note, "d": jsonb(form)})


def read_case(db: Any, archive: Archive, case: dict, *, reader: Callable[..., tuple[dict, str]] = call_reader,
              fetch_paper: Callable[[Any, Archive, dict], dict] | None = None) -> str:
    """Read one claimed case; the status it ends in."""
    try:
        if case["origin"] == "paper" and not case.get("r2_key"):
            from collectors.cases import paper

            case = (fetch_paper or paper.fetch_source)(db, archive, case)
        data = source_bytes(case, archive)
        try:
            blocks = content.blocks_for(data, case.get("mime") or "", case.get("file_name"))
        except content.Unreadable as exc:
            raise ReadFailed(str(exc)) from exc
        ingredients = watched_ingredients(db)
        reading, model = reader(blocks, ingredients)
    except ReadFailed as exc:
        return _fail(db, case, exc)
    store_reading(db, case, reading, model, ingredients)
    log.info("case %s read: %s", case["ref"], ", ".join(schema.missing(schema.form_from_reading(reading)))
             or "all four minimum criteria")
    return "to_confirm"


def read_waiting(db: Any, archive: Archive, *, case_id: str | None = None, limit: int = 10,
                 reader: Callable[..., tuple[dict, str]] = call_reader) -> dict[str, int]:
    """Read the waiting cases (or the one asked for), oldest first; counts per final status."""
    counts: dict[str, int] = {}
    done: list[str] = []   # a case put back in the queue waits for the next run, not the next turn of this loop
    for _ in range(1 if case_id else limit):
        case = claim(db, case_id, done)
        if case is None:
            break
        done.append(str(case["id"]))
        try:
            status = read_case(db, archive, case, reader=reader)
        except Exception as exc:  # noqa: BLE001 - one case never stops the others
            log.exception("case %s: unexpected error", case.get("ref"))
            status = _fail(db, case, ReadFailed(f"Unexpected error: {type(exc).__name__}", passing=True))
        counts[status] = counts.get(status, 0) + 1
    return counts
