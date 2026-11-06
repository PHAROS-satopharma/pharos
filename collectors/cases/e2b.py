"""The ICH E2B(R3) file of a confirmed case: an HL7 v3 ICSR message (MCCI_IN200100UV01 batch around one
PORR_IN049016UV report), made from the confirmed form when a reviewer asks for it (``ask_case_e2b()``, 0059).

The file carries: the batch and message headers (N.1, N.2); the case (C.1: the sender's safety report id and the
worldwide unique case id ``<country>-<sender>-<case number>``, day zero as the date first received, the date of
the most recent information, the type of report, seriousness overall); the primary source (C.2: name,
qualification, organisation, country); the literature reference (C.4); the patient (D: initials, age, age group,
sex, weight, birth date, history); each reaction (E.i: the verbatim words in their language, the MedDRA LLT code
and version, onset, end, outcome, the seriousness criteria); each product (G.k: name, active ingredient, role,
dose as text, route as text, indication, dates, batch, action taken); the narrative and the reporter's comment (H).

MedDRA codes are typed by the team on the case screen (PHAROS holds no MedDRA licence and never invents a code):
a reaction without an LLT code and version stops the file, as do the four minimum criteria and a missing
seriousness decision, and the reason is shown on the case. The file is archived under
``reports/cases/<case number>/`` (``put_named(revise=True)``: a new file never replaces an older one) with its
SHA-256 kept on the case.

Before the first real submission the file must pass the ICH E2B(R3) schema and the receiving authority's gateway
test; until then it is a prepared draft, which the case screen says. The ICH code-list OIDs used are gathered in
``OID`` below so that check changes one place.

Environment: ``PHAROS_E2B_SENDER`` (the company's sender identifier at the authority, default ``SATOPHARMA``),
``PHAROS_E2B_RECEIVER`` (default ``EDA``).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from collectors.cases import schema
from collectors.core.archive import Archive
from collectors.core.db import jsonb

log = logging.getLogger("collectors.cases.e2b")

HL7 = "urn:hl7-org:v3"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
MEDDRA = "2.16.840.1.113883.6.163"
UCUM = "2.16.840.1.113883.6.8"
ISO_COUNTRY = "1.0.3166.1.2.2"
ISO_LANG = "1.0.639.2"

# The ICH E2B(R3) Implementation Guide's object identifiers (code lists and id roots).
OID = {
    "batch_id": "2.16.840.1.113883.3.989.2.1.3.22",
    "message_id": "2.16.840.1.113883.3.989.2.1.3.1",
    "sender_report_id": "2.16.840.1.113883.3.989.2.1.3.1",
    "worldwide_id": "2.16.840.1.113883.3.989.2.1.3.2",
    "batch_sender": "2.16.840.1.113883.3.989.2.1.3.13",
    "batch_receiver": "2.16.840.1.113883.3.989.2.1.3.14",
    "message_sender": "2.16.840.1.113883.3.989.2.1.3.11",
    "message_receiver": "2.16.840.1.113883.3.989.2.1.3.12",
    "report_type": "2.16.840.1.113883.3.989.2.1.1.2",
    "qualification": "2.16.840.1.113883.3.989.2.1.1.6",
    "age_group": "2.16.840.1.113883.3.989.2.1.1.9",
    "outcome": "2.16.840.1.113883.3.989.2.1.1.11",
    "role": "2.16.840.1.113883.3.989.2.1.1.13",
    "action": "2.16.840.1.113883.3.989.2.1.1.15",
    "observation": "2.16.840.1.113883.3.989.2.1.1.19",
    "organizer": "2.16.840.1.113883.3.989.2.1.1.20",
    "source_report": "2.16.840.1.113883.3.989.2.1.1.22",
    "sex": "1.0.5218",
}

REPORT_TYPE = {"spontaneous": "1", "study": "2", "other": "3", "literature": "1"}
QUALIFICATION = {"physician": "1", "pharmacist": "2", "other_health_professional": "3", "lawyer": "4",
                 "consumer": "5"}
AGE_GROUP = {"neonate": "1", "infant": "2", "child": "3", "adolescent": "4", "adult": "5", "elderly": "6"}
AGE_UNIT = {"year": "a", "month": "mo", "week": "wk", "day": "d", "hour": "h", "decade": "10.a"}
SEX = {"male": "1", "female": "2"}
OUTCOME = {"recovered": "1", "recovering": "2", "not_recovered": "3", "recovered_with_sequelae": "4",
           "fatal": "5", "unknown": "0"}
ROLE = {"suspect": "1", "concomitant": "2", "interacting": "3"}
ACTION = {"withdrawn": "1", "dose_reduced": "2", "dose_increased": "3", "not_changed": "4", "unknown": "0",
          "not_applicable": "9"}
# Observation codes (E.i.3.2 seriousness criteria and the patient's observations).
OBS = {"death": "34", "life_threatening": "21", "hospitalisation": "33", "disability": "35",
       "congenital_anomaly": "12", "other_medically_important": "26", "age": "3", "age_group": "4",
       "weight": "7", "reaction": "29", "history": "18", "outcome": "27", "pregnant": "1", "action": "8", "causality": "20",
       "serious": "seriousness"}

_DAY = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_LLT = re.compile(r"^\d{8}$")
_VERSION = re.compile(r"^\d{1,2}\.\d$")


class CannotMake(Exception):
    """The case lacks what the file needs; the message is for the reviewer."""


def hl7_date(value: Any) -> str | None:
    """'2026-05-03' → '20260503', '2026-05' → '202605', '2026' → '2026'; anything else None."""
    v = str(value or "").strip()
    return v.replace("-", "") if _DAY.match(v) else None


def problems(case: dict) -> list[str]:
    """Why the file cannot be made yet, in plain words (empty when it can)."""
    data = case.get("data") or {}
    out = [f"the case has no {m} yet" for m in schema.missing(data)]
    if case.get("serious") is None:
        out.append("seriousness is not decided")
    if case.get("status") not in ("confirmed", "sent"):
        out.append("the case is not confirmed")
    for i, r in enumerate(data.get("reactions") or [], 1):
        if not (r.get("verbatim") or "").strip():
            continue
        if not _LLT.match(str(r.get("meddra_llt_code") or "").strip()):
            out.append(f"reaction {i} needs its MedDRA LLT code (8 digits)")
        if not _VERSION.match(str(r.get("meddra_version") or "").strip()):
            out.append(f"reaction {i} needs its MedDRA version (e.g. 28.1)")
    return out


def _sender() -> str:
    return (os.environ.get("PHAROS_E2B_SENDER") or "SATOPHARMA").strip()


def _receiver() -> str:
    return (os.environ.get("PHAROS_E2B_RECEIVER") or "EDA").strip()


def build_xml(case: dict, now: datetime | None = None) -> bytes:
    """The E2B(R3) message of one case. Raises ``CannotMake`` when ``problems()`` finds any."""
    from lxml import etree

    issues = problems(case)
    if issues:
        raise CannotMake("The E2B file needs: " + "; ".join(issues) + ".")
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d%H%M%S")
    data = case["data"]
    ref = case["ref"]
    country = (data.get("country") or "EG").upper()[:2]
    sender, receiver = _sender(), _receiver()
    worldwide = f"{country}-{sender}-{ref}"

    def el(parent: Any, tag: str, attrs: dict | None = None, text: str | None = None) -> Any:
        node = etree.SubElement(parent, f"{{{HL7}}}{tag}",
                                {k: str(v) for k, v in (attrs or {}).items() if v is not None})
        if text is not None:
            node.text = text
        return node

    def code(parent: Any, tag: str, value: str, system: str, **extra: str) -> Any:
        return el(parent, tag, {"code": value, "codeSystem": system, **extra})

    def value(parent: Any, xsi_type: str, attrs: dict | None = None, text: str | None = None) -> Any:
        node = el(parent, "value", attrs, text)
        node.set(f"{{{XSI}}}type", xsi_type)
        return node

    def observation(parent: Any, obs: str) -> Any:
        o = el(el(parent, "subjectOf2"), "observation", {"moodCode": "EVN", "classCode": "OBS"})
        code(o, "code", OBS[obs], OID["observation"])
        return o

    root = etree.Element(f"{{{HL7}}}MCCI_IN200100UV01", {"ITSVersion": "XML_1.0"},
                         nsmap={None: HL7, "xsi": XSI})
    root.set(f"{{{XSI}}}schemaLocation", f"{HL7} MCCI_IN200100UV01.xsd")
    el(root, "id", {"extension": f"{sender}-{ref}-{stamp}", "root": OID["batch_id"]})
    el(root, "creationTime", {"value": stamp})
    el(root, "responseModeCode", {"code": "D"})
    el(root, "interactionId", {"root": "2.16.840.1.113883.1.6", "extension": "MCCI_IN200100UV01"})

    msg = el(root, "PORR_IN049016UV")
    el(msg, "id", {"extension": f"{sender}-{ref}-{stamp}", "root": OID["message_id"]})
    el(msg, "creationTime", {"value": stamp})
    el(msg, "interactionId", {"root": "2.16.840.1.113883.1.6", "extension": "PORR_IN049016UV"})
    el(msg, "processingCode", {"code": "P"})
    el(msg, "processingModeCode", {"code": "T"})
    el(msg, "acceptAckCode", {"code": "AL"})
    rec = el(el(msg, "receiver", {"typeCode": "RCV"}), "device", {"classCode": "DEV", "determinerCode": "INSTANCE"})
    el(rec, "id", {"extension": receiver, "root": OID["message_receiver"]})
    snd = el(el(msg, "sender", {"typeCode": "SND"}), "device", {"classCode": "DEV", "determinerCode": "INSTANCE"})
    el(snd, "id", {"extension": sender, "root": OID["message_sender"]})

    act = el(msg, "controlActProcess", {"classCode": "CACT", "moodCode": "EVN"})
    code(act, "code", "PORR_TE049016UV", "2.16.840.1.113883.1.18")
    el(act, "effectiveTime", {"value": stamp})
    inv = el(el(act, "subject", {"typeCode": "SUBJ"}), "investigationEvent", {"classCode": "INVSTG", "moodCode": "EVN"})
    el(inv, "id", {"extension": f"{sender}-{ref}", "root": OID["sender_report_id"]})       # C.1.1
    el(inv, "id", {"extension": worldwide, "root": OID["worldwide_id"]})                   # C.1.8.1
    code(inv, "code", "PAT_ADV_EVNT", "2.16.840.1.113883.5.4")
    if data.get("narrative"):
        el(inv, "text", None, str(data["narrative"])[:100000])                             # H.1
    el(inv, "statusCode", {"code": "active"})
    el(el(inv, "effectiveTime"), "low", {"value": hl7_date(str(case["day_zero"]))})        # C.1.4
    el(inv, "availabilityTime", {"value": hl7_date(str(case["day_zero"]))})                # C.1.5

    if data.get("literature_reference"):                                                    # C.4.r.1
        ref_node = el(el(inv, "reference", {"typeCode": "REFR"}), "document",
                      {"classCode": "DOC", "moodCode": "EVN"})
        code(ref_node, "code", "1", "2.16.840.1.113883.3.989.2.1.1.27")
        el(ref_node, "bibliographicDesignationText", None, str(data["literature_reference"])[:500])

    # D: the patient, the reactions and the products sit in the adverse event assessment.
    assess = el(el(inv, "component", {"typeCode": "COMP"}), "adverseEventAssessment",
                {"classCode": "INVSTG", "moodCode": "EVN"})
    role = el(el(assess, "subject1", {"typeCode": "SBJ"}), "primaryRole", {"classCode": "INVSBJ"})
    patient = data.get("patient") or {}
    person = el(role, "player1", {"classCode": "PSN", "determinerCode": "INSTANCE"})
    el(person, "name", None, (patient.get("initials") or "UNK")[:60])                      # D.1
    if patient.get("sex") in SEX:
        code(person, "administrativeGenderCode", SEX[patient["sex"]], OID["sex"])          # D.5
    if hl7_date(patient.get("birth_date")):
        el(person, "birthTime", {"value": hl7_date(patient["birth_date"])})               # D.2.1
    if patient.get("age_value") is not None and patient.get("age_unit") in AGE_UNIT:
        value(observation(role, "age"), "PQ", {"value": patient["age_value"],
                                               "unit": AGE_UNIT[patient["age_unit"]]})    # D.2.2
    if patient.get("age_group") in AGE_GROUP:
        value(observation(role, "age_group"), "CE",
              {"code": AGE_GROUP[patient["age_group"]], "codeSystem": OID["age_group"]})  # D.2.3
    if patient.get("weight_kg") is not None:
        value(observation(role, "weight"), "PQ", {"value": patient["weight_kg"], "unit": "kg"})  # D.3
    if patient.get("pregnant") is True:
        value(observation(role, "pregnant"), "BL", {"value": "true"})
    if patient.get("medical_history"):
        value(observation(role, "history"), "ED", None, str(patient["medical_history"])[:10000])  # D.7.2

    # E.i: reactions.
    reaction_ids: list[str] = []
    for i, r in enumerate(data.get("reactions") or [], 1):
        if not (r.get("verbatim") or "").strip():
            continue
        rid = f"{ref}-R{i}"
        reaction_ids.append(rid)
        o = observation(role, "reaction")
        el(o, "id", {"root": "2.16.840.1.113883.3.989.5.1.2.2.1.1", "extension": rid})
        times = el(o, "effectiveTime")
        if hl7_date(r.get("onset_date")):
            el(times, "low", {"value": hl7_date(r["onset_date"])})                         # E.i.4
        if hl7_date(r.get("end_date")):
            el(times, "high", {"value": hl7_date(r["end_date"])})                          # E.i.5
        v = value(o, "CE", {"code": str(r["meddra_llt_code"]).strip(), "codeSystem": MEDDRA,
                            "codeSystemVersion": str(r["meddra_version"]).strip()})        # E.i.2.1
        orig = el(v, "originalText", {"language": (r.get("verbatim_language") or "en")[:3]},
                  str(r["verbatim"])[:250])                                                 # E.i.1.1
        if r.get("english") and r.get("english") != r.get("verbatim"):
            orig.addnext(etree.Comment(f" E.i.1.2 translation: {str(r['english'])[:250]} "))
        loc = el(el(o, "location", {"typeCode": "LOC"}), "locatedEntity", {"classCode": "LOCE"})
        code(el(loc, "locatedPlace", {"classCode": "COUNTRY", "determinerCode": "INSTANCE"}), "code",
             country, ISO_COUNTRY)
        criteria = set(r.get("criteria") or [])
        for c in ("death", "life_threatening", "hospitalisation", "disability", "congenital_anomaly",
                  "other_medically_important"):                                            # E.i.3.2
            crit = el(el(o, "outboundRelationship2", {"typeCode": "PERT"}), "observation",
                      {"classCode": "OBS", "moodCode": "EVN"})
            code(crit, "code", OBS[c], OID["observation"])
            if c in criteria:
                value(crit, "BL", {"value": "true"})
            else:
                value(crit, "BL", {"nullFlavor": "NI"})
        if r.get("outcome") in OUTCOME:                                                     # E.i.7
            out = el(el(o, "outboundRelationship2", {"typeCode": "PERT"}), "observation",
                     {"classCode": "OBS", "moodCode": "EVN"})
            code(out, "code", OBS["outcome"], OID["observation"])
            value(out, "CE", {"code": OUTCOME[r["outcome"]], "codeSystem": OID["outcome"]})

    # G.k: products.
    organizer = el(el(role, "subjectOf2", {"typeCode": "SBJ"}), "organizer",
                   {"classCode": "CATEGORY", "moodCode": "EVN"})
    code(organizer, "code", "4", OID["organizer"])                                          # drug information
    drug_ids: list[tuple[str, str]] = []
    for k, p in enumerate(data.get("products") or [], 1):
        if not (p.get("name") or "").strip():
            continue
        did = f"{ref}-D{k}"
        drug_ids.append((did, p.get("role") or "suspect"))
        sa = el(el(organizer, "component", {"typeCode": "COMP"}), "substanceAdministration",
                {"classCode": "SBADM", "moodCode": "EVN"})
        el(sa, "id", {"root": "2.16.840.1.113883.3.989.5.1.2.2.1.2", "extension": did})
        if p.get("dose") or p.get("route"):
            el(sa, "text", None, "; ".join(x for x in (p.get("dose"), p.get("route")) if x)[:2000])  # G.k.4.r
        times = el(sa, "effectiveTime")
        if hl7_date(p.get("start_date")):
            el(times, "low", {"value": hl7_date(p["start_date"])})                          # G.k.4.r.4
        if hl7_date(p.get("stop_date")):
            el(times, "high", {"value": hl7_date(p["stop_date"])})                          # G.k.4.r.5
        kind = el(el(sa, "consumable", {"typeCode": "CSM"}), "instanceOfKind", {"classCode": "INST"})
        if p.get("batch"):
            lot = el(kind, "productInstanceInstance", {"classCode": "MMAT", "determinerCode": "INSTANCE"})
            el(lot, "lotNumberText", None, str(p["batch"])[:35])                            # G.k.4.r.7
        product = el(kind, "kindOfProduct", {"classCode": "MMAT", "determinerCode": "KIND"})
        el(product, "name", None, str(p["name"])[:250])                                     # G.k.2.2
        if p.get("active_ingredient"):
            ing = el(el(product, "ingredient", {"classCode": "ACTI"}), "ingredientSubstance",
                     {"classCode": "MMAT", "determinerCode": "KIND"})
            el(ing, "name", None, str(p["active_ingredient"])[:250])                       # G.k.2.3.r.1
        if p.get("indication"):
            ind = el(el(sa, "inboundRelationship", {"typeCode": "RSON"}), "observation",
                     {"classCode": "OBS", "moodCode": "EVN"})
            code(ind, "code", "19", OID["observation"])
            el(value(ind, "CE", {"nullFlavor": "OTH"}), "originalText", None, str(p["indication"])[:250])  # G.k.7.r.1
        if p.get("action_taken") in ACTION:
            act_node = el(el(sa, "inboundRelationship", {"typeCode": "CAUS"}), "act",
                          {"classCode": "ACT", "moodCode": "EVN"})
            code(act_node, "code", ACTION[p["action_taken"]], OID["action"])                # G.k.8

    # G.k.1: the role of each product, as the causality link between products and the adverse event.
    for did, r in drug_ids:
        ca = el(el(assess, "component", {"typeCode": "COMP"}), "causalityAssessment",
                {"classCode": "OBS", "moodCode": "EVN"})
        code(ca, "code", OBS["causality"], OID["observation"])
        value(ca, "CE", {"code": ROLE.get(r, "1"), "codeSystem": OID["role"]})
        el(el(el(ca, "subject2", {"typeCode": "SUBJ"}), "productUseReference",
              {"classCode": "SBADM", "moodCode": "EVN"}), "id",
           {"root": "2.16.840.1.113883.3.989.5.1.2.2.1.2", "extension": did})

    # H.2 the reporter's comment.
    if data.get("causality"):
        comment = el(el(assess, "component1", {"typeCode": "COMP"}), "observationEvent",
                     {"classCode": "OBS", "moodCode": "EVN"})
        code(comment, "code", "10", OID["observation"])
        value(comment, "ED", None, str(data["causality"])[:20000])

    # C.2.r: the primary source.
    reporter = data.get("reporter") or {}
    src = el(el(el(inv, "outboundRelationship", {"typeCode": "SPRT"}), "relatedInvestigation",
                {"classCode": "INVSTG", "moodCode": "EVN"}), "subjectOf2", {"typeCode": "SUBJ"})
    author = el(el(el(src, "controlActEvent", {"classCode": "CACT", "moodCode": "EVN"}), "author",
                   {"typeCode": "AUT"}), "assignedEntity", {"classCode": "ASSIGNED"})
    if reporter.get("qualification") in QUALIFICATION:
        code(author, "code", QUALIFICATION[reporter["qualification"]], OID["qualification"])  # C.2.r.4
    if reporter.get("name"):
        el(el(author, "assignedPerson", {"classCode": "PSN", "determinerCode": "INSTANCE"}), "name",
           None, str(reporter["name"])[:100])                                                 # C.2.r.1
    if reporter.get("organisation"):
        org = el(author, "representedOrganization", {"classCode": "ORG", "determinerCode": "INSTANCE"})
        el(org, "name", None, str(reporter["organisation"])[:60])                           # C.2.r.2.1
    rc = (reporter.get("country") or country).upper()[:2]
    code(el(el(author, "asLocatedEntity", {"classCode": "LOCE"}), "location",
            {"classCode": "COUNTRY", "determinerCode": "INSTANCE"}), "code", rc, ISO_COUNTRY)  # C.2.r.3

    # C.1.3 type of report and C.1.7 seriousness, as characteristics of the case.
    char = el(el(inv, "subjectOf2", {"typeCode": "SUBJ"}), "investigationCharacteristic",
              {"classCode": "OBS", "moodCode": "EVN"})
    code(char, "code", "1", "2.16.840.1.113883.3.989.2.1.1.23")
    value(char, "CE", {"code": REPORT_TYPE.get(data.get("report_type") or "", "3"),
                       "codeSystem": OID["report_type"]})
    serious = el(el(inv, "subjectOf2", {"typeCode": "SUBJ"}), "investigationCharacteristic",
                 {"classCode": "OBS", "moodCode": "EVN"})
    code(serious, "code", "3", "2.16.840.1.113883.3.989.2.1.1.23")
    value(serious, "BL", {"value": "true" if case.get("serious") else "false"})

    rcv = el(el(root, "receiver", {"typeCode": "RCV"}), "device", {"classCode": "DEV", "determinerCode": "INSTANCE"})
    el(rcv, "id", {"extension": receiver, "root": OID["batch_receiver"]})
    snd = el(el(root, "sender", {"typeCode": "SND"}), "device", {"classCode": "DEV", "determinerCode": "INSTANCE"})
    el(snd, "id", {"extension": sender, "root": OID["batch_sender"]})
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def make(db: Any, archive: Archive, case_id: str | None = None) -> dict[str, int]:
    """Make the file of every case that asked for one (or the one given); counts made / failed."""
    counts = {"made": 0, "failed": 0}
    while True:
        with db.transaction():
            case = db.fetchone(
                """select * from safety_case
                    where e2b_status = 'queued' and (%(c)s::uuid is null or id = %(c)s::uuid)
                    order by updated_at limit 1 for update skip locked""", {"c": case_id})
            if case is None:
                return counts
            try:
                xml = build_xml(case)
            except CannotMake as exc:
                db.execute("""update safety_case set e2b_status = 'failed', e2b_error = %(e)s,
                                     updated_at = clock_timestamp() where id = %(id)s""",
                           {"e": str(exc)[:1000], "id": case["id"]})
                db.execute("""insert into case_event (case_id, step, from_status, to_status, comment)
                              values (%(id)s, 'e2b_failed', %(s)s, %(s)s, %(e)s)""",
                           {"id": case["id"], "s": case["status"], "e": str(exc)[:1000]})
                counts["failed"] += 1
                log.warning("case %s: %s", case["ref"], exc)
            else:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
                sha, key = archive.put_named(f"reports/cases/{case['ref']}/{case['ref']}-E2B-R3-{stamp}.xml", xml,
                                             "application/xml", revise=True)
                db.execute("""update safety_case set e2b_status = 'made', e2b_error = null, e2b_r2_key = %(k)s,
                                     e2b_sha256 = %(s)s, e2b_at = now(), updated_at = clock_timestamp()
                               where id = %(id)s""", {"k": key, "s": sha, "id": case["id"]})
                db.execute("""insert into case_event (case_id, step, from_status, to_status, comment, data)
                              values (%(id)s, 'e2b_made', %(st)s, %(st)s, %(c)s, %(d)s)""",
                           {"id": case["id"], "st": case["status"], "c": f"E2B(R3) file made, SHA-256 {sha}",
                            "d": jsonb(case["data"])})
                counts["made"] += 1
                log.info("case %s: E2B file %s", case["ref"], key)
        if case_id:
            return counts
