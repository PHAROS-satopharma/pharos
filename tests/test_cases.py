"""PHAROS — individual case reports (collectors/cases, migration 0059): the form's rules, the documents the reader is
given, the reading stored for the reviewer, the forwarded-mail intake and the E2B(R3) file. No network, no API
call: the reader and the mailbox are fakes; every message here is constructed."""

from __future__ import annotations

import base64
import io
import json
import types
import zipfile

import pytest
from lxml import etree

from collectors.cases import content, e2b, mail, read, schema
from collectors.core.archive import Archive, sha256_hex
from tests.test_run_imap import FakeIMAP

CASE_ID = "00000000-0000-0000-0000-0000000053c1"

FULL = {
    "report_type": "spontaneous", "country": "EG", "narrative": "A 34-year-old woman developed jaundice.",
    "causality": "Probably related", "literature_reference": None,
    "patient": {"initials": "A.M.", "sex": "female", "age_value": 34, "age_unit": "year", "weight_kg": 61.5,
                "pregnant": None, "birth_date": None, "medical_history": "Asthma", "age_group": None},
    "reporter": {"name": "Dr Adel", "qualification": "physician", "organisation": "Cairo Hospital", "country": "EG",
                 "email": None, "phone": None},
    "products": [{"name": "Casoxicam 8 mg", "active_ingredient": "lornoxicam", "role": "suspect",
                  "dose": "8 mg twice daily", "route": "oral", "indication": "back pain", "start_date": "2026-10-01",
                  "stop_date": "2026-10-05", "action_taken": "withdrawn", "batch": "B1234"},
                 {"name": "Paracetamol", "active_ingredient": "paracetamol", "role": "concomitant"}],
    "reactions": [{"verbatim": "اصفرار العين", "verbatim_language": "ar", "english": "yellow eyes",
                   "meddra_llt_code": "10023126", "meddra_version": "28.1", "onset_date": "2026-10-04",
                   "end_date": None, "outcome": "recovering", "criteria": ["hospitalisation"]}],
}


# ───────────────────────────── the form ─────────────────────────────

def test_the_four_minimum_criteria():
    assert schema.missing(FULL) == []
    assert schema.missing({}) == ["patient", "reporter", "product", "reaction"]
    only_concomitant = {**FULL, "products": [{"name": "Paracetamol", "role": "concomitant"}]}
    assert schema.missing(only_concomitant) == ["product"]
    # A paper's reference identifies the reporter.
    paper = {**FULL, "reporter": {}, "literature_reference": "Adel A. Jaundice after lornoxicam. 2026."}
    assert schema.missing(paper) == []
    blank = {**FULL, "patient": {"initials": "  ", "sex": None}, "reactions": [{"verbatim": ""}]}
    assert schema.missing(blank) == ["patient", "reaction"]


def test_the_schema_has_no_nullable_field_and_closes_every_object():
    text = json.dumps(schema.CASE_SCHEMA)
    assert "anyOf" not in text and '"null"' not in text

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema.CASE_SCHEMA)


def test_the_reading_is_normalised_into_the_form():
    reading = {"is_case": True, "report_type": "spontaneous", "serious": "yes", "notes": "",
               "patient": {"initials": "A.M.", "age_value": "34", "weight_kg": "61,5", "pregnant": "no", "sex": ""},
               "reactions": [{"verbatim": "rash", "serious": "yes", "criteria": []}],
               "evidence": [{"field": "patient.age_value", "quote": "aged 34", "page": 0}]}
    form = schema.form_from_reading(reading)
    assert form["patient"] == {"initials": "A.M.", "age_value": 34, "weight_kg": 61.5, "pregnant": False,
                               "sex": None}
    assert form["reactions"][0]["serious"] is True
    assert form["notes"] is None
    assert "serious" not in form and "evidence" not in form and "is_case" not in form
    assert schema.normalise(reading)["evidence"][0]["page"] is None


# ───────────────────────────── what the reader is given ─────────────────────────────

def _docx(paragraphs: list[str]) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_pdf_and_photos_go_in_as_they_are():
    pdf = b"%PDF-1.7 fake"
    [block] = content.blocks_for(pdf, content.PDF, "report.pdf")
    assert block["type"] == "document" and block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == pdf
    [img] = content.blocks_for(b"\x89PNG....", "image/png")
    assert img["type"] == "image" and img["source"]["media_type"] == "image/png"


def test_a_word_file_is_read_as_its_text():
    [block] = content.blocks_for(_docx(["Patient: A.M., 34 years", "Reaction: jaundice"]), content.DOCX, "r.docx")
    assert block["source"]["data"] == "Patient: A.M., 34 years\nReaction: jaundice"
    with pytest.raises(content.Unreadable):
        content.blocks_for(b"PK\x03\x04 not a zip", content.DOCX)


def test_a_word_file_cannot_reach_outside_itself():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    assert "root:" not in content.docx_text(buf.getvalue())


def test_a_saved_email_brings_its_attachments():
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "Dr Adel <adel@hospital.example>"
    msg["Subject"] = "Adverse reaction"
    msg.set_content("Please see the attached report.")
    msg.add_attachment(b"%PDF-1.7 fake", maintype="application", subtype="pdf", filename="report.pdf")
    msg.add_attachment(b"MZ\x00\x00", maintype="application", subtype="octet-stream", filename="tool.exe")
    blocks = content.blocks_for(msg.as_bytes(), content.EML, "fwd.eml")
    assert "Please see the attached report." in blocks[0]["source"]["data"]
    assert "Subject: Adverse reaction" in blocks[0]["source"]["data"]
    assert blocks[1]["source"]["media_type"] == "application/pdf"
    assert "tool.exe" in blocks[-1]["source"]["data"]          # named, never passed on
    assert len(blocks) == 3


def test_an_unknown_kind_is_refused():
    with pytest.raises(content.Unreadable):
        content.blocks_for(b"\x00\x01", "application/x-msdownload")


# ───────────────────────────── the reading ─────────────────────────────

def _json(v):
    """A jsonb parameter back as Python: psycopg's Jsonb, or its JSON text where psycopg is absent."""
    return v.obj if hasattr(v, "obj") else json.loads(v)


class CaseDb:
    """One case, its events and the ingredients, in memory; answers the SQL read.py sends."""

    def __init__(self, case: dict):
        self.case = case
        self.events: list[dict] = []

    def transaction(self):
        import contextlib

        return contextlib.nullcontext(self)

    def fetchall(self, sql, params=None):
        assert "from ingredient" in sql
        return [{"id": "ing-1", "inn_en": "Lornoxicam", "terms": ["casoxicam", "xefo"]},
                {"id": "ing-2", "inn_en": "Carvedilol", "terms": []}]

    def fetchone(self, sql, params=None):
        if sql.lstrip().startswith("update safety_case set status = 'reading'"):
            c = self.case
            if c["status"] != "queued" or str(c["id"]) in params["done"]:
                return None
            c.update(status="reading", read_attempts=c["read_attempts"] + 1)
            return dict(c)
        raise AssertionError(sql)

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("update safety_case set status = 'to_confirm'"):
            self.case.update(status="to_confirm", extracted=_json(params["x"]), data=_json(params["d"]),
                             ingredient_id=params["ing"], reader_model=params["m"])
        elif s.startswith("update safety_case set status = %(s)s"):
            self.case.update(status=params["s"], read_error=params["e"])
        elif s.startswith("insert into case_event"):
            self.events.append({"sql": s, **params})
        else:
            raise AssertionError(sql)


@pytest.fixture
def stored(tmp_path):
    archive = Archive(tmp_path)
    data = b"%PDF-1.7 a report"
    sha, key = archive.put(data, content.PDF)
    case = {"id": CASE_ID, "ref": "CASE-2026-001", "origin": "upload", "status": "queued", "read_attempts": 0,
            "r2_key": key, "sha256": sha, "mime": content.PDF, "file_name": "report.pdf", "ingredient_id": None}
    return CaseDb(case), archive


def test_a_reading_waits_for_the_reviewer_with_its_ingredient(stored):
    db, archive = stored
    given = {}

    def reader(blocks, ingredients):
        given["blocks"], given["names"] = blocks, [i["inn_en"] for i in ingredients]
        return {"is_case": True, "serious": "yes", **json.loads(json.dumps(FULL, default=str)),
                "products": [{"name": "Casoxicam 8 mg", "active_ingredient": "", "role": "suspect"}],
                "evidence": []}, "claude-opus-5-5"

    assert read.read_waiting(db, archive, reader=reader) == {"to_confirm": 1}
    assert given["blocks"][0]["type"] == "document" and given["names"] == ["Lornoxicam", "Carvedilol"]
    assert db.case["status"] == "to_confirm" and db.case["ingredient_id"] == "ing-1"   # by its brand name
    assert db.case["extracted"]["serious"] == "yes"                                     # kept as the reader said
    assert "serious" not in db.case["data"]                                             # the reviewer decides
    assert [e["sql"].split("values")[1].split(",")[1].strip() for e in db.events] == ["'read'"]


def test_a_tampered_original_is_never_read(stored):
    db, archive = stored
    db.case["sha256"] = "0" * 64
    called = []
    assert read.read_waiting(db, archive, reader=lambda *a: called.append(a)) == {"failed": 1}
    assert not called and "does not match its SHA-256" in db.case["read_error"]


def test_a_passing_failure_waits_for_the_next_run_and_the_third_fails(stored):
    db, archive = stored

    def down(*a):
        raise read.ReadFailed("The reader could not be reached (APIConnectionError).", passing=True)

    assert read.read_waiting(db, archive, reader=down) == {"queued": 1}     # tried once this run, not three times
    assert db.case["read_attempts"] == 1 and not db.events
    db.case["read_attempts"] = read.MAX_ATTEMPTS - 1
    assert read.read_waiting(db, archive, reader=down) == {"failed": 1}
    assert db.events and "read_failed" in db.events[0]["sql"]


def test_the_ingredient_is_left_to_the_reviewer_when_two_are_named():
    ings = [{"id": "a", "inn_en": "Lornoxicam", "names": ["lornoxicam"]},
            {"id": "b", "inn_en": "Carvedilol", "names": ["carvedilol"]}]
    one = {"products": [{"name": "Lornoxicam 8 mg", "role": "suspect"}, {"name": "Carvedilol", "role": "concomitant"}]}
    two = {"products": [{"name": "Lornoxicam", "role": "suspect"}, {"name": "Carvedilol", "role": "suspect"}]}
    part = {"products": [{"name": "Lornoxicamide", "role": "suspect"}]}
    assert read.guess_ingredient(one, ings) == "a"
    assert read.guess_ingredient(two, ings) is None
    assert read.guess_ingredient(part, ings) is None


def test_the_api_call_asks_for_the_form_and_checks_why_it_stopped(monkeypatch):
    sent = {}

    class Stream:
        def __init__(self, message):
            self.message = message

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return self.message

    def client_for(stop_reason, text='{"is_case": true}'):
        message = types.SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5-5",
                                        content=[types.SimpleNamespace(type="text", text=text)])

        def stream(**kwargs):
            sent.update(kwargs)
            return Stream(message)

        return types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream))

    reading, model = read.call_reader([{"type": "text", "text": "x"}], [{"inn_en": "Lornoxicam"}],
                                      client_for("end_turn"))
    assert reading == {"is_case": True} and model == "claude-opus-5-5"
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": schema.CASE_SCHEMA}
    assert "Lornoxicam" in sent["messages"][0]["content"][-1]["text"]
    with pytest.raises(read.ReadFailed, match="declined"):
        read.call_reader([], [], client_for("refusal"))
    with pytest.raises(read.ReadFailed, match="too long"):
        read.call_reader([], [], client_for("max_tokens"))


# ───────────────────────────── forwarded mail ─────────────────────────────

YAHOO = ["yahoo.com"]
PASS = b"Authentication-Results: atlas1.mail.yahoo.com; dmarc=pass header.from=satopharma.com\r\n"


def _forward(subject: str, sender: str = "sama.mosaad@satopharma.com", auth: bytes = PASS) -> bytes:
    return auth + (f"From: Sama <{sender}>\r\nTo: pharos@satopharma.com\r\nSubject: {subject}\r\n"
                   "Date: Thu, 05 Nov 2026 23:30:00 +0000\r\nContent-Type: text/plain\r\n\r\n"
                   "A patient had jaundice after Casoxicam.\r\n").encode()


class MailDb:
    def __init__(self):
        self.inbound, self.cases, self.events = [], [], []

    def transaction(self):
        import contextlib

        return contextlib.nullcontext(self)

    def fetchall(self, sql, params=None):
        assert "from person" in sql
        return [{"id": "p-sama", "email": "sama.mosaad@satopharma.com"}]

    def fetchone(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("select 1 from safety_case"):
            return {"x": 1} if any(c["sha"] == params["s"] for c in self.cases) else None
        if s.startswith("insert into inbound_email"):
            self.inbound.append(params)
            return {"id": f"in-{len(self.inbound)}"}
        if s.startswith("insert into safety_case"):
            self.cases.append(params)
            return {"id": f"case-{len(self.cases)}", "ref": f"CASE-2026-00{len(self.cases)}"}
        raise AssertionError(sql)

    def execute(self, sql, params=None):
        assert "insert into case_event" in sql
        self.events.append(params)


def test_a_forwarded_report_opens_a_case_and_other_mail_is_untouched(tmp_path):
    imap = FakeIMAP({b"1": _forward("FW: CASE jaundice"),
                     b"2": _forward("FW: meeting"),                                   # no CASE
                     b"3": _forward("CASE", sender="someone@example.com"),             # not on the team
                     b"4": _forward("Showcase", sender="sama.mosaad@satopharma.com")})  # CASE inside a word
    db = MailDb()
    counts = mail.collect(db, Archive(tmp_path), connect=lambda: imap, authserv_domains=YAHOO)
    assert counts == {"opened": 1, "held": 0}
    assert imap.seen == {b"1"}
    [case] = db.cases
    assert case["p"] == "p-sama" and case["d"] == "2026-11-06"       # 01:30 Cairo on 6 November
    assert case["sha"] == sha256_hex(imap.messages[b"1"]) and case["k"].startswith("inbound/")
    assert db.inbound[0]["f"] == "sama.mosaad@satopharma.com"
    assert db.events[0]["p"] == "p-sama"


def test_a_forged_team_address_is_held_unread(tmp_path):
    forged = b"Authentication-Results: atlas1.mail.yahoo.com; dmarc=fail header.from=satopharma.com\r\n"
    imap = FakeIMAP({b"1": _forward("CASE", auth=forged)})
    db = MailDb()
    assert mail.collect(db, Archive(tmp_path), connect=lambda: imap, authserv_domains=YAHOO) == {"opened": 0,
                                                                                                "held": 1}
    assert not imap.seen and not db.cases


def test_a_message_already_opened_is_not_opened_twice(tmp_path):
    raw = _forward("CASE 1")
    db = MailDb()
    db.cases.append({"sha": sha256_hex(raw)})
    imap = FakeIMAP({b"1": raw})
    mail.collect(db, Archive(tmp_path), connect=lambda: imap, authserv_domains=YAHOO)
    assert len(db.cases) == 1 and imap.seen == {b"1"}


# ───────────────────────────── the E2B(R3) file ─────────────────────────────

CONFIRMED = {"id": CASE_ID, "ref": "CASE-2026-001", "status": "confirmed", "serious": True,
             "day_zero": "2026-11-04", "data": FULL}
NS = {"h": "urn:hl7-org:v3"}


def test_the_e2b_file_carries_the_case():
    root = etree.fromstring(e2b.build_xml(CONFIRMED))
    assert root.tag == "{urn:hl7-org:v3}MCCI_IN200100UV01"
    ids = [i.get("extension") for i in root.iterfind(".//h:investigationEvent/h:id", NS)]
    assert ids == ["SATOPHARMA-CASE-2026-001", "EG-SATOPHARMA-CASE-2026-001"]
    assert root.find(".//h:investigationEvent/h:effectiveTime/h:low", NS).get("value") == "20261104"
    reaction = root.find(".//h:value[@codeSystem='2.16.840.1.113883.6.163']", NS)
    assert reaction.get("code") == "10023126" and reaction.get("codeSystemVersion") == "28.1"
    orig = reaction.find("h:originalText", NS)
    assert orig.text == "اصفرار العين" and orig.get("language") == "ar"
    assert root.find(".//h:player1/h:name", NS).text == "A.M."
    assert root.find(".//h:player1/h:administrativeGenderCode", NS).get("code") == "2"
    names = [n.text for n in root.iterfind(".//h:kindOfProduct/h:name", NS)]
    assert names == ["Casoxicam 8 mg", "Paracetamol"]
    assert root.find(".//h:lotNumberText", NS).text == "B1234"
    assert root.findtext(".//h:investigationEvent/h:text", namespaces=NS).startswith("A 34-year-old woman")
    roles = [v.get("code") for v in root.iterfind(".//h:causalityAssessment/h:value", NS)]
    assert roles == ["1", "2"]


def test_the_e2b_file_is_refused_without_meddra_or_seriousness():
    no_code = {**CONFIRMED, "data": {**FULL, "reactions": [{**FULL["reactions"][0], "meddra_llt_code": ""}]}}
    with pytest.raises(e2b.CannotMake, match="reaction 1 needs its MedDRA LLT code"):
        e2b.build_xml(no_code)
    with pytest.raises(e2b.CannotMake, match="seriousness is not decided"):
        e2b.build_xml({**CONFIRMED, "serious": None})
    with pytest.raises(e2b.CannotMake, match="not confirmed"):
        e2b.build_xml({**CONFIRMED, "status": "to_confirm"})
    assert e2b.problems(CONFIRMED) == []


def test_partial_dates_keep_their_precision():
    assert e2b.hl7_date("2026-05-03") == "20260503"
    assert e2b.hl7_date("2026-05") == "202605"
    assert e2b.hl7_date("2026") == "2026"
    assert e2b.hl7_date("May 2026") is None
