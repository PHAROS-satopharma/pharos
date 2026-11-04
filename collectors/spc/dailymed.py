"""PHAROS — United States, DailyMed (NLM) structured product labels.

Source ``spc-dailymed``; country US; English.

* Discovery: ``https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name=<INN>&pagesize=100&page=<n>``
  → ``{"data": [{"setid", "title", "spl_version", "published_date"}], "metadata": {"total_pages"}}``.
  Only human prescription labels are wanted; titles containing "[" + labeler are kept as published.
  (An ingredient with no US product, such as lornoxicam, simply yields none.)
* Snapshot: ``https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/<setid>.xml`` (HL7 SPL,
  namespace ``urn:hl7-org:v3``). Sections are found by LOINC code
  (``section/code/@code``, mapped in ``sections.US_LOINC``) and their text is every ``text``
  node below them. ``effectiveTime/@value`` (YYYYMMDD) is the label date.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import quote
from xml.etree import ElementTree as ET

from collectors.spc.common import Product, Snapshot, terms_for
from collectors.spc.sections import US_LOINC

SOURCE_ID = "spc-dailymed"
COUNTRY = "US"
LANG = "en"
API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
NS = {"v3": "urn:hl7-org:v3"}
MAX_PAGES = 5


def discover(ctx, ingredient: dict) -> list[Product]:
    found: dict[str, Product] = {}
    for term in terms_for(ingredient, "en")[:3]:
        page = 1
        while page <= MAX_PAGES:
            f = ctx.get(f"{API}/spls.json?drug_name={quote(term)}&pagesize=100&page={page}",
                        accept="application/json")
            if f.status != 200:
                break
            data = f.json()
            for row in data.get("data") or []:
                setid = row.get("setid")
                if not setid or setid in found:
                    continue
                found[setid] = Product(
                    national_id=setid, product_name=(row.get("title") or setid).strip(),
                    url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
                    country_code=COUNTRY,
                    extra={"spl_version": row.get("spl_version"),
                           "published_date": row.get("published_date")})
            total = int((data.get("metadata") or {}).get("total_pages") or 1)
            if page >= total:
                break
            page += 1
    return list(found.values())


def _text(node) -> str:
    parts = []
    for t in node.iter():
        if t.text and t.text.strip():
            parts.append(t.text.strip())
        if t.tail and t.tail.strip():
            parts.append(t.tail.strip())
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def parse_spl(xml: bytes) -> tuple[dict[str, str], date | None]:
    root = ET.fromstring(xml)
    sections: dict[str, str] = {}
    for sec in root.iter("{urn:hl7-org:v3}section"):
        code = sec.find("v3:code", NS)
        key = US_LOINC.get(code.get("code")) if code is not None else None
        if not key:
            continue
        texts = [_text(t) for t in sec.iter("{urn:hl7-org:v3}text")]
        body = "\n".join(t for t in texts if t)
        if body:
            sections[key] = (sections[key] + "\n" + body) if key in sections else body
    eff = root.find("v3:effectiveTime", NS)
    when = None
    if eff is not None and re.fullmatch(r"\d{8}", eff.get("value", "")[:8] or ""):
        v = eff.get("value")[:8]
        try:
            when = date(int(v[:4]), int(v[4:6]), int(v[6:8]))
        except ValueError:
            when = None
    return sections, when


def snapshot(ctx, product: dict) -> Snapshot | None:
    url = f"{API}/spls/{product['national_id']}.xml"
    f = ctx.get(url, accept="application/xml")
    if f.status != 200 or not f.content:
        return None
    try:
        sections, when = parse_spl(f.content)
    except ET.ParseError:
        return None
    if not sections:
        return None
    return Snapshot(sections=sections, doc_date=when, lang=LANG, source_url=url,
                    original_sha256=f.sha256)
