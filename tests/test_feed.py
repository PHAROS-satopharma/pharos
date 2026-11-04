"""Feed-like parsers against the real fixtures captured from each regulator (tests/fixtures/<source>/).

Options come from collectors/sources.yaml, so a change to a source's filters is tested here too.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from collectors.core.registry import load_catalogue
from collectors.parsers import govuk, hc_recalls, openfda_enforcement, pubmed
from collectors.parsers.base import ParseError
from collectors.parsers.feed import parse_feed

FIX = Path(__file__).resolve().parent / "fixtures"
_, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}


def fixture(rel: str) -> bytes:
    return (FIX / rel).read_bytes()


def feed(source_id: str, rel: str) -> list:
    src = CFG[source_id]
    return parse_feed(fixture(rel), src, src.url)


def test_fda_medwatch_drops_devices_and_types_recalls():
    items = feed("fda-medwatch", "fda-medwatch/rss.xml")
    assert len(items) == 3  # 12 of the 15 entries are /medical-devices/ pages
    assert all("/medical-devices/" not in i.url for i in items)
    by_title = {i.title.split(" ")[0]: i for i in items}
    assert by_title["Par"].doc_type == "recall"
    assert by_title["Par"].published == date(2026, 10, 14)  # "Wed, 14 Oct 2026 00:00:00 EDT"
    assert by_title["FDA"].doc_type == "safety_alert"
    assert all(i.lang == "en" for i in items)


def test_bfarm_german_feed():
    items = feed("bfarm-rhb", "bfarm-rhb/rss.xml")
    assert len(items) == 15
    first = items[0]
    assert first.title.startswith("Rote-Hand-Brief zu Caelyx: Fläschchenstopfen")
    assert first.url.endswith("/RHB/2026/rhb-caelyx.html")
    assert first.published == date(2026, 10, 30)
    assert first.lang == "de" and first.doc_type == "dhpc"
    info = [i for i in items if i.title.startswith("Informationsbrief")]
    assert info and all(i.doc_type == "safety_alert" for i in info)


def test_basg_keeps_official_notices_only():
    items = feed("basg-whatsnew", "basg-whatsnew/rss.xml")
    urls = {i.url for i in items}
    assert any(u.endswith("/mynzepli-40-mg-ml-injektionsloesung-in-einer-fertigspritze") for u in urls)
    assert any(u.endswith("/maxi-kalz-vitd3-500-mg-400-ie-kautabletten") for u in urls)
    assert not any("west-nil" in u or "dengue" in u or "chikungunya" in u for u in urls)
    assert not any("medsafety-week" in u for u in urls)  # outside the included paths
    rms = [i for i in items if "RMS NEWS" in i.title]
    assert rms and all(i.doc_type == "newsletter" for i in rms)
    assert all(i.published and i.published.year == 2026 for i in items)


def test_aemps_categories():
    items = feed("aemps-feed", "aemps-feed/feed.xml")
    titles = [i.title for i in items]
    assert not any("MedSafetyWeek" in t for t in titles)          # campaign, not a safety category
    assert not any("Veterinarios" in t for t in titles)
    bulletin = next(i for i in items if i.title.startswith("Boletín sobre Seguridad"))
    assert bulletin.doc_type == "newsletter" and bulletin.lang == "es"
    estradiol = next(i for i in items if "estradiol" in i.title)
    assert estradiol.doc_type == "recall"                           # category "Defectos de calidad"
    assert "Seguridad" in next(i for i in items if "Dexcom" in i.title).structured["categories"]


def test_hsa_categories_and_local_dates():
    items = feed("hsa-announcements", "hsa-announcements/rss.xml")
    assert len(items) == 11  # 9 DHPC letters + 2 product recalls; press releases etc. are dropped
    tetra = next(i for i in items if i.title.startswith("Recall of Tetrabenazine"))
    assert tetra.doc_type == "recall"
    first = items[0]
    assert first.doc_type == "dhpc"
    # "Wed, 04 Nov 2026 00:00:00 +0800" is 4 November in Singapore, not 3 November UTC.
    assert first.published == date(2026, 11, 4)
    assert sum(i.doc_type == "dhpc" for i in items) == 9


def test_not_a_feed_raises():
    with pytest.raises(ParseError):
        parse_feed(b"<html><body>Access denied</body></html>", CFG["bfarm-rhb"], CFG["bfarm-rhb"].url)


# ───────────────────────────── GOV.UK (MHRA) ─────────────────────────────

def test_mhra_feeds_and_content_api():
    dsu = feed("mhra-dsu", "mhra-dsu/feed.atom")
    assert len(dsu) == 15 and all(i.doc_type == "safety_update" for i in dsu)
    assert any(i.title.startswith("IXCHIQ Chikungunya vaccine") for i in dsu)

    alerts = feed("mhra-alerts", "mhra-alerts/feed.atom")
    assert len(alerts) == 15
    ler = next(i for i in alerts if "lercanidipine" in i.url)
    data = json.loads(fixture("mhra-alerts/content-lercanidipine.json"))
    govuk.apply_content(ler, data, CFG["mhra-alerts"])
    assert ler.doc_type == "recall"                       # alert_type medicines-recall-notification
    assert ler.published == date(2026, 10, 29)            # metadata.issued_date
    assert ler.body_text.startswith("Accord-UK Ltd is recalling one batch of Lercanidipine")
    assert len(ler.attachment_urls) == 1 and ler.attachment_urls[0].lower().endswith(".pdf")
    assert ler.structured["metadata"]["alert_type"] == "medicines-recall-notification"
    assert govuk.path_of(ler.url).startswith("/drug-device-alerts/class-2-medicines-recall-accord")


def test_govuk_shape_change_raises():
    alerts = feed("mhra-alerts", "mhra-alerts/feed.atom")
    with pytest.raises(ParseError):
        govuk.apply_content(alerts[0], {"title": "x"}, CFG["mhra-alerts"])


# ───────────────────────────── openFDA, Health Canada, PubMed ─────────────────────────────

def test_openfda_enforcement_records():
    data = json.loads(fixture("fda-enforcement/enforcement-limit5.json"))
    base = CFG["fda-enforcement"].url
    items = [openfda_enforcement.record_to_item(r, base) for r in data["results"]]
    assert len(items) == 5
    first = items[0]
    assert first.external_id == "D-0062-2027"
    assert first.published == date(2026, 10, 28)          # report_date 20261028
    assert first.doc_type == "recall" and first.lang == "en"
    assert "recall_number:%22D-0062-2027%22" in first.url
    assert "Reason for recall:" in first.body_text
    with pytest.raises(ParseError):
        openfda_enforcement.record_to_item({"product_description": "x"}, base)


def test_health_canada_keeps_health_products():
    rows = json.loads(fixture("hc-recalls/HCRSAMOpenData-slice.json"))
    items = hc_recalls.parse_records(rows, CFG["hc-recalls"])
    orgs = {"drugs and health products", "marketed health products"}
    assert items
    assert all(i.structured["Organization"].casefold() in orgs for i in items)
    assert not any(i.structured["Category"] == "Veterinary drugs" for i in items)
    assert all(i.doc_type == ("safety_alert" if i.structured["Organization"] == "Marketed health products"
                              else "recall") for i in items)
    assert all(i.url.startswith("https://") and "\\/" not in i.url for i in items)
    wanted = sum(1 for r in rows if r["Organization"] in ("Drugs and health products",
                                                           "Marketed health products")
                 and r["Category"] != "Veterinary drugs")
    assert len(items) == wanted


def test_pubmed_esummary():
    search = json.loads(fixture("pubmed/esearch-lornoxicam.json"))
    assert search["esearchresult"]["idlist"]
    data = json.loads(fixture("pubmed/esummary.json"))
    items = pubmed.parse_esummary(data, "lornoxicam")
    assert [i.external_id for i in items] == ["42846100", "42770875", "42859397"]
    first = items[0]
    assert first.url == "https://pubmed.ncbi.nlm.nih.gov/42846100/"
    assert first.doc_type == "literature"
    assert first.published == date(2026, 10, 7)          # sortpubdate 2026/10/07
    assert first.structured["query_term"] == "lornoxicam"
    with pytest.raises(ParseError):
        pubmed.parse_esummary({"error": "x"}, "lornoxicam")
