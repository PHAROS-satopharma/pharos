"""PHAROS — a drafted root cause and CAPA for a deviation or an audit observation (migration 0109).

A reviewer asks on the Quality tab; the quality-draft Edge Function records the ask (quality_draft_ask) and starts
.github/workflows/quality-draft.yml with only the draft's id. This reads what is recorded on the deviation (its
description, dates, impact, level, the six investigation answers, the root cause so far, its CAPAs) or on the
observation (its text, grade, root cause so far, the audit and its CAPAs), and asks the reader — the same Claude
model the case reports use, signed in by federation (collectors/core/claude.py) — for four short texts: the root
cause, the corrective action, the preventive action, and what the draft could not know and must be checked. The
draft is only text on the tab: it changes no record. She uses it, changed or not, through the usual forms.

    python -m collectors.quality_drafts --draft ID   draft this one now (the workflow, on her click)
    python -m collectors.quality_drafts --waiting    draft every one still waiting (the 4-hourly collection's
                                                     safety net when GitHub could not be reached from the app)

A failure is recorded on the draft (the tab shows it and offers to try again); the exit status is 1 only when the
database cannot be reached.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Any, Callable

log = logging.getLogger("collectors.quality_drafts")

MODEL = "claude-opus-5-5"
MAX_TOKENS = 4000
MAX_ATTEMPTS = 3
STALE = "20 minutes"        # a draft started this long ago and never finished (the run died) is taken again
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

SYSTEM = """You help the pharmacovigilance team of Sato Pharma (Egypt) write the root cause and the CAPA of a \
deviation (their SOP PV-SOP-021) or of an audit observation (PV-SOP-022). The Qualified Person for \
Pharmacovigilance reads your draft, changes it and decides; nothing you write is recorded until she does.

Rules:
- Use only the facts given. Never invent a name, a date, a number, a system or an event. Where a fact the root \
cause depends on is missing, say in "to_check" what must be found out, and keep the root cause to what the facts \
support.
- The root cause is the underlying reason the process allowed this to happen (a missing step, an unclear SOP, no \
deputy, no check, no training), not a restatement of what happened and not a person's fault.
- The corrective action fixes this occurrence and its consequences. The preventive action stops it happening \
again. Each is concrete: what is done, by which role (never a person's name), and a relative time ("within 5 \
working days"). Prefer one or two actions each. Where a CAPA already exists, do not repeat it.
- Plain English, short sentences, no headings, no markdown, no bullet symbols. Each field at most 80 words."""

SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string", "description": "The underlying reason, from the facts given."},
        "corrective_action": {"type": "string", "description": "What fixes this occurrence, by role, with a time."},
        "preventive_action": {"type": "string", "description": "What stops it happening again, by role, with a time."},
        "to_check": {"type": "string", "description": "What the draft could not know and must be checked first."},
    },
    "required": ["root_cause", "corrective_action", "preventive_action", "to_check"],
    "additionalProperties": False,
}

FIELDS = tuple(SCHEMA["required"])

INVESTIGATION = (
    ("inv_cause", "What was the cause?"),
    ("inv_people_time", "Who was involved, the time and the duration?"),
    ("inv_reoccur", "Could it reoccur?"),
    ("inv_similar", "Have similar deviations occurred in the past?"),
    ("inv_other_impact", "Any impact on other products or processes?"),
    ("inv_training", "Training status of the people involved?"),
)
LEVEL = {1: "1 (no impact)", 2: "2 (may affect regulatory compliance)", 3: "3 (impact on patient safety)"}


class DraftFailed(Exception):
    """A draft that could not be made, in words for the tab. ``passing``: worth trying again later."""

    def __init__(self, message: str, *, passing: bool = False):
        super().__init__(message)
        self.passing = passing


# ───────────────────────────── what is recorded ─────────────────────────────

DEVIATION_SQL = """
select d.ref, d.title, d.description, d.occurred_on, d.detected_on, d.level, d.patient_safety,
       d.regulatory_compliance, d.document_quality, d.inv_cause, d.inv_people_time, d.inv_reoccur, d.inv_similar,
       d.inv_other_impact, d.inv_training, d.root_cause, d.status,
       coalesce((select json_agg(json_build_object('ref', c.ref, 'corrective', c.corrective_action,
                                                   'preventive', c.preventive_action, 'status', c.status)
                                 order by c.year, c.serial)
                   from capa c where c.deviation_id = d.id), '[]') as capas
  from deviation d where d.id = %(id)s"""

OBSERVATION_SQL = """
select o.number, o.text, o.grade, o.root_cause, a.kind, a.title as audit_title, a.auditor,
       a.report_received_on,
       coalesce((select json_agg(json_build_object('ref', c.ref, 'corrective', c.corrective_action,
                                                   'preventive', c.preventive_action, 'status', c.status)
                                 order by c.year, c.serial)
                   from capa c where c.observation_id = o.id), '[]') as capas
  from audit_observation o join audit a on a.id = o.audit_id where o.id = %(id)s"""


def _capa_lines(capas: Any) -> list[str]:
    rows = json.loads(capas) if isinstance(capas, str) else (capas or [])
    if not rows:
        return ["CAPAs already recorded: none."]
    out = ["CAPAs already recorded:"]
    for c in rows:
        parts = [f"{c.get('ref')} ({c.get('status')})"]
        if c.get("corrective"):
            parts.append(f"corrective: {c['corrective']}")
        if c.get("preventive"):
            parts.append(f"preventive: {c['preventive']}")
        out.append("- " + "; ".join(parts))
    return out


def facts(kind: str, rec: dict) -> str:
    """What is recorded, as the text the reader is given. Nothing else about the company is sent."""
    if kind == "deviation":
        impact = [w for k, w in (("patient_safety", "patient safety"),
                                 ("regulatory_compliance", "regulatory compliance"),
                                 ("document_quality", "document quality")) if rec.get(k)]
        lines = [
            f"A deviation, {rec.get('ref')}: {rec.get('title')}",
            f"What happened: {rec.get('description')}",
            f"Happened on: {rec.get('occurred_on') or 'not known'}. Detected on: {rec.get('detected_on')}.",
            f"Potential impact on: {', '.join(impact) if impact else 'none marked'}.",
            f"Level set by QA: {LEVEL.get(rec.get('level'), 'not set yet')}.",
            "The investigation so far:",
        ]
        lines += [f"- {q} {rec.get(f) or '(not answered yet)'}" for f, q in INVESTIGATION]
        lines.append(f"Root cause written so far: {rec.get('root_cause') or '(none yet)'}")
    else:
        kind_word = "An internal audit" if rec.get("kind") == "internal" else "An external audit"
        lines = [
            f"An audit observation: {kind_word}, \"{rec.get('audit_title')}\", by {rec.get('auditor')}, "
            f"report received {rec.get('report_received_on') or 'not yet'}.",
            f"Observation {rec.get('number')}, graded {rec.get('grade')}: {rec.get('text')}",
            f"Root cause written so far: {rec.get('root_cause') or '(none yet)'}",
        ]
    lines += _capa_lines(rec.get("capas"))
    lines.append("Write the four fields of the draft from these facts only.")
    return "\n".join(lines)


# ───────────────────────────── the reader ─────────────────────────────

def call_drafter(text: str, client: Any = None) -> tuple[dict, str]:
    """The reader's four fields and the model that wrote them."""
    import anthropic

    from collectors.core import claude

    client = client or claude.client()
    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as exc:
        raise DraftFailed(f"The reader could not be reached ({type(exc).__name__}). Try again.",
                          passing=True) from exc
    except anthropic.WorkloadIdentityError as exc:
        raise DraftFailed(f"PHAROS could not sign in to the reader: {str(exc)[:300]}", passing=True) from exc
    except anthropic.APIStatusError as exc:
        raise DraftFailed(f"The reader refused the request (HTTP {exc.status_code}).") from exc
    if message.stop_reason == "refusal":
        raise DraftFailed("The reader declined to draft this. Write it by hand.")
    if message.stop_reason == "max_tokens":
        raise DraftFailed("The draft did not finish. Try again.", passing=True)
    body = next((b.text for b in message.content if b.type == "text"), "")
    try:
        draft = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DraftFailed("The reader's answer was not complete. Try again.", passing=True) from exc
    clean = {f: str(draft.get(f) or "").strip() for f in FIELDS}
    if not clean["root_cause"]:
        raise DraftFailed("The reader gave no root cause. Try again.", passing=True)
    return clean, getattr(message, "model", None) or MODEL


# ───────────────────────────── one draft ─────────────────────────────

def claim(db: Any, draft_id: str) -> dict | None:
    """Takes the draft for this run (queued, or started long ago by a run that died, and under the attempt limit),
    counting the attempt. None when it is not waiting."""
    return db.fetchone(
        f"""update quality_draft set status = 'drafting', started_at = now(), attempts = attempts + 1
             where id = %(id)s and attempts < {MAX_ATTEMPTS}
               and (status = 'queued' or (status = 'drafting' and started_at < now() - interval '{STALE}'))
         returning id::text as id, record_kind, record_id::text as record_id, attempts""", {"id": draft_id})


def draft_one(db: Any, draft_id: str, *, drafter: Callable[[str], tuple[dict, str]] = call_drafter) -> str:
    """Makes one draft; returns its status after ('ready', 'failed', 'queued' to try again, or 'skipped')."""
    d = claim(db, draft_id)
    if d is None:
        log.info("draft %s is not waiting", draft_id)
        return "skipped"
    rec = db.fetchone(DEVIATION_SQL if d["record_kind"] == "deviation" else OBSERVATION_SQL, {"id": d["record_id"]})
    try:
        if rec is None:
            raise DraftFailed("The record is no longer there.")
        fields, model = drafter(facts(d["record_kind"], rec))
    except DraftFailed as exc:
        again = exc.passing and int(d["attempts"]) < MAX_ATTEMPTS
        db.execute(
            """update quality_draft
                  set status = %(s)s, error = %(e)s, finished_at = case when %(s)s = 'failed' then now() end
                where id = %(id)s""",
            {"s": "queued" if again else "failed", "e": str(exc), "id": draft_id})
        log.warning("draft %s: %s", draft_id, exc)
        return "queued" if again else "failed"
    db.execute(
        """update quality_draft
              set status = 'ready', root_cause = %(r)s, corrective_action = %(c)s, preventive_action = %(p)s,
                  to_check = %(t)s, model = %(m)s, error = null, finished_at = now()
            where id = %(id)s""",
        {"r": fields["root_cause"], "c": fields["corrective_action"] or None,
         "p": fields["preventive_action"] or None, "t": fields["to_check"] or None, "m": model, "id": draft_id})
    log.info("draft %s ready (%s %s)", draft_id, d["record_kind"], d["record_id"])
    return "ready"


def waiting(db: Any) -> list[str]:
    rows = db.fetchall(
        f"""select id::text as id from quality_draft
             where attempts < {MAX_ATTEMPTS}
               and (status = 'queued' or (status = 'drafting' and started_at < now() - interval '{STALE}'))
             order by asked_at""")
    return [r["id"] for r in rows]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m collectors.quality_drafts", description=__doc__.split("\n\n")[0])
    ap.add_argument("--draft", help="draft this one now")
    ap.add_argument("--waiting", action="store_true", help="draft every one still waiting")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.draft and not UUID.match(args.draft):
        ap.error("not a draft id")
    if not args.draft and not args.waiting:
        ap.error("give --draft ID or --waiting")
    from collectors.core import claude
    from collectors.core.db import Db

    if not claude.configured():
        log.warning("no way to sign in to the reader in this run; the drafts wait")
        return 0
    try:
        db = Db()
    except Exception as exc:  # noqa: BLE001 - no database is the one failure that fails the run
        log.error("the database cannot be reached: %s", exc)
        return 1
    ids = [args.draft] if args.draft else waiting(db)
    for i in ids:
        try:
            draft_one(db, i)
        except Exception as exc:  # noqa: BLE001 - one draft never stops the others
            log.error("draft %s could not be made: %s", i, exc)
    log.info("%d drafts looked at", len(ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
