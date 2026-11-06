"""PHAROS — DHPC coverage audit of 5 Nov 2026: every reference regulator's letters list is read.

Each test pins one gap found by checking the regulator's own DHPC list against what PHAROS read.
Fixtures were saved from the live sites on 5 Nov 2026; titles are asserted exactly as published.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from collectors.core.models import Item
from collectors.core.registry import load_catalogue
from collectors.parsers import aemps_dhpc, ansm, basg_dhpc, cbg_dhpc, govuk, lakemedelsverket, pmda
from collectors.parsers.feed import parse_feed
from tests.fakes_a2 import FakeCtx, fetched, source

REGULATORS, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}
# MHRA is listed from GOV.UK's search API (tests/test_govuk_search.py): its newest page, then an empty one.
MHRA_LIST = {govuk.search_url(CFG["mhra-alerts"], 0): "mhra-search/alerts-0.json",
             "https://www.gov.uk/api/search.json*": b'{"results": [], "total": 100}'}


# ───────────────────── Austria: BASG's RSS carries no DHPC ─────────────────────

BASG = "https://www.basg.gv.at/gesundheitsberufe/sicherheitsinformationen-dhpc"


def test_basg_dhpc_page_is_read():
    src = CFG["basg-dhpc"]
    assert src.enabled and src.parser == "basg_dhpc" and src.url == BASG
    items = basg_dhpc.parse_list(fetched("basg-dhpc/list.html", BASG), BASG, src)
    assert len(items) == 20
    first = items[0]
    assert first.url == ("https://www.basg.gv.at/fileadmin/redakteure/06_Gesundheitsberufe/DHPC/"
                         "2026/261103_Caelyx.pdf")
    assert first.external_id == first.url and first.attachment_urls == [first.url]
    assert first.published == date(2026, 11, 3)
    assert first.doc_type == "dhpc" and first.lang == "de"
    assert first.title.startswith("Wichtige Information des Bundesamtes für Sicherheit im "
                                  "Gesundheitswesen über folgenden Qualitätsmangel")
    # The product is named only in the file name here, so it is kept with the text screened.
    assert first.structured["file_name"] == "261103_Caelyx" and "Caelyx" in first.body_text
    assert [i.published for i in items[:2]] == [date(2026, 11, 3), date(2026, 10, 12)]
    assert "Ocrevus" in items[1].title


# ───────────────── Germany: vaccine and blood-product letters come from PEI ─────────────────

def test_pei_letters_are_read():
    assert any(r["id"] == "PEI" and r["country_code"] == "DE" for r in REGULATORS)
    src = CFG["pei-rhb"]
    assert src.enabled and src.regulator_id == "PEI" and src.schedule == "4h"
    items = parse_feed(fetched("pei-rhb/feed.xml").content, src, src.url)
    by_title = {i.title: i for i in items}
    assert len(items) == 8
    respreeza = by_title["Rote-Hand-Brief: Respreeza (humaner Alpha-1-Proteinase-Inhibitor)"]
    assert respreeza.doc_type == "dhpc" and respreeza.published == date(2026, 10, 30)
    assert by_title["Rote-Hand-Brief: Ocrevus (Ocrelizumab)"].doc_type == "dhpc"
    assert by_title["Rote-Hand-Brief: Ixchiq (Chikungunya-Impfstoff)"].published == date(2026, 7, 14)
    assert by_title["Informationsbrief von Grifols Deutschland GmbH: Gamunex 10%"].doc_type == "safety_alert"
    assert by_title["Sicherheitsbewertung von Aluminium in Therapieallergenen"].doc_type == "safety_update"


# ─────────────────── France: vaccine DHPCs are tagged "Vaccins", not "Médicaments" ───────────────────

def test_ansm_reads_vaccine_dhpcs():
    src = CFG["ansm-securite"]
    items = ansm.parse_list(fetched("ansm-securite/list_medicaments_vaccins.html", src.url), src.url, src)
    assert len(items) == 20
    assert {i.structured["health_product"] for i in items} == {"Médicaments", "Vaccins"}
    ixchiq = next(i for i in items if i.title.startswith("Vaccin Ixchiq"))
    assert ixchiq.published == date(2026, 7, 15)


# ─────────────────── Japan: the companies' letters (適正使用等に関するお知らせ) ───────────────────

LETTERS = "https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/properly-use-alert/0004.html"
PROPER = "https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/properly-use-alert/0002.html"


def test_pmda_company_letters_are_read():
    src = CFG["pmda-company-letters"]
    assert src.enabled and src.url == LETTERS and pmda.page_kind(src) == "letters"
    items = pmda.parse_letters(fetched("pmda-letters/company.html", LETTERS), LETTERS, src)
    assert len(items) == 96
    first = items[0]
    assert first.title == "フィブラストスプレー250、同スプレー500の適正使用に関するお願い"
    assert first.url == "https://www.pmda.go.jp/files/000283053.pdf"
    assert first.published == date(2026, 10, 1) and first.doc_type == "dhpc" and first.lang == "ja"
    assert first.structured["company"] == "科研製薬（株）"
    # An updated letter keeps its PDF: the update month makes it a new item for review.
    comirnaty = items[1]
    assert comirnaty.title == "コミナティ筋注製剤 間違い接種防止のお願い"
    assert comirnaty.published == date(2026, 9, 1)
    assert comirnaty.external_id == "pmda-letter:000271056:2026-09-01"
    assert len({i.external_id for i in items}) == len(items)


def test_pmda_proper_use_requests_are_read():
    src = CFG["pmda-proper-use"]
    assert src.enabled and src.url == PROPER and pmda.page_kind(src) == "msi"
    items = pmda.parse_msi(fetched("pmda-letters/pmda.html", PROPER), PROPER, src)
    assert len(items) == 18
    assert items[0].title == "GLP-1受容体作動薬及びGIP/GLP-1受容体作動薬の適正使用のお願い"
    assert items[0].published == date(2026, 10, 1) and items[0].doc_type == "safety_alert"


# ─────────────────── UK: the DHPCs are listed inside the monthly Safety Roundup ───────────────────

def test_mhra_roundup_body_carries_the_letters():
    data = json.loads(fetched("mhra-alerts/content-roundup-october-2026.json").content)
    url = "https://www.gov.uk/drug-device-alerts/mhra-safety-roundup-october-2026"
    item = Item(external_id=url, url=url, title="MHRA Safety Roundup: October 2026", published=None,
                doc_type="safety_alert", lang="en")
    govuk.apply_content(item, data, CFG["mhra-alerts"])
    assert item.doc_type == "newsletter"                  # alert_type mhra-safety-round-up
    section = item.body_text[item.body_text.index("Direct Healthcare Professional Communications"):]
    assert "Guanfacine prolonged-release tablets" in section


def test_mhra_roundup_letters_are_items_of_their_own():
    roundup = "https://www.gov.uk/drug-device-alerts/mhra-safety-roundup-october-2026"
    api = "https://www.gov.uk/api/content/drug-device-alerts/mhra-safety-roundup-october-2026"
    ctx = FakeCtx({**MHRA_LIST, api: "mhra-alerts/content-roundup-october-2026.json"}, backfill=True)
    items = govuk.list_items(ctx, CFG["mhra-alerts"])
    letters = [i for i in items if (i.structured or {}).get("roundup") == roundup]
    assert len(letters) == 8                              # the October 2026 DHPC section
    guanfacine = next(i for i in letters if i.title.startswith("Guanfacine"))
    assert guanfacine.title.startswith("Guanfacine prolonged-release tablets (PL 49718/0136-0142): "
                                       "Important safety information missing")
    assert guanfacine.doc_type == "dhpc" and guanfacine.published == date(2026, 10, 27)
    assert guanfacine.url.endswith("/DMRC_PROC-40963122_Guanfacine_DHCP_V4_APPROVED_20261008.pdf")
    assert guanfacine.external_id == guanfacine.url and guanfacine.attachment_urls == [guanfacine.url]
    assert any(i.external_id == "/drug-device-alerts/mhra-safety-roundup-october-2026" for i in items)
    assert ("FORGET", api, None) in ctx.requests          # the roundup's own detail is read in full
    assert govuk.fetch_detail(ctx, CFG["mhra-alerts"], guanfacine) is guanfacine



def test_one_bad_roundup_never_loses_the_feed():
    # Audit of 6 Nov 2026: a roundup whose content-API answer is not JSON (a 200 maintenance page) raised
    # ParseError out of list_items, so the run kept none of the feed's alerts and drug safety updates.
    api = "https://www.gov.uk/api/content/drug-device-alerts/mhra-safety-roundup-october-2026"
    ctx = FakeCtx({**MHRA_LIST, api: b"<html><body>GOV.UK is down for maintenance</body></html>"}, backfill=True)
    ctx.list_errors = []
    items = govuk.list_items(ctx, CFG["mhra-alerts"])
    assert len(items) == 100                              # every listed entry kept, no letters this run
    assert not [i for i in items if (i.structured or {}).get("roundup")]
    assert any("mhra-safety-roundup-october-2026" in e and "ParseError" in e for e in ctx.list_errors)


def test_a_roundup_that_cannot_be_fetched_is_a_note_not_a_failure():
    from collectors.core.context import FetchError

    api = "https://www.gov.uk/api/content/drug-device-alerts/mhra-safety-roundup-october-2026"

    class Timeout(FakeCtx):
        def get(self, url, **kw):
            if url == api:
                raise FetchError(503, url)                # three server errors in a row
            return super().get(url, **kw)

    ctx = Timeout(dict(MHRA_LIST), backfill=True)
    ctx.list_errors = []
    items = govuk.list_items(ctx, CFG["mhra-alerts"])
    assert any(i.external_id == "/drug-device-alerts/mhra-safety-roundup-october-2026" for i in items)
    assert any("mhra-safety-roundup-october-2026" in e and "FetchError" in e for e in ctx.list_errors)


# ─────────────────── Spain: the letters are only in AEMPS's « Cartas de seguridad » list ───────────────────

def test_aemps_letters_are_read():
    src = CFG["aemps-dhpc"]
    assert src.enabled and src.parser == "aemps_dhpc"
    rows = json.loads(fetched("aemps-dhpc/mostrar.json").content)
    assert len(rows) == 412
    items = aemps_dhpc.parse_rows(rows, src, now=datetime(2026, 11, 5, 20, 0, tzinfo=aemps_dhpc.MADRID))
    assert len(items) == 10                               # the last 400 days of an archive back to 2007
    ocrevus = items[-1]
    assert ocrevus.title.startswith("OCREVUS (Ocrelizumab): NUEVO RIESGO DE DAÑO HEPÁTICO")
    assert ocrevus.published == date(2026, 10, 8) and ocrevus.doc_type == "dhpc" and ocrevus.lang == "es"
    assert ocrevus.url == "https://docswebaemps.aemps.es/PDF/DHPC-OCREVUS-1026.pdf"
    assert ocrevus.attachment_urls == [ocrevus.url] and ocrevus.external_id == "aemps-dhpc:5680"
    # A letter scheduled for later is not public yet.
    early = aemps_dhpc.parse_rows(rows, src, now=datetime(2026, 10, 8, 6, 0, tzinfo=aemps_dhpc.MADRID))
    assert "aemps-dhpc:5680" not in {i.external_id for i in early}


# ─────────────────── Netherlands: CBG's letter pages, from its sitemap ───────────────────

CBG_MAP = "https://www.cbg-meb.nl/sitemap/"
CAELYX = "https://www.cbg-meb.nl/documenten/2026/10/30/dhpc-caelyx"


def test_cbg_letters_are_read():
    src = CFG["cbg-dhpc"]
    assert src.enabled and src.url == CBG_MAP + "1.xml"
    ctx = FakeCtx({CBG_MAP + "1.xml": "cbg-dhpc/sitemap-1.xml", CBG_MAP + "2.xml": "cbg-dhpc/sitemap-2.xml",
                   CAELYX: "cbg-dhpc/dhpc-caelyx.html"})
    items = cbg_dhpc.list_items(ctx, src)                 # 3.xml is missing here: reading just ends
    by_url = {i.url: i for i in items}
    assert len(items) == 7 and all(i.doc_type == "dhpc" for i in items)
    assert by_url["https://www.cbg-meb.nl/documenten/2026/07/dhpc-ixchiq"].published == date(2026, 7, 1)
    assert "https://www.cbg-meb.nl/documenten/2026/07/16/dhpc-tavneos" in by_url
    caelyx = cbg_dhpc.fetch_detail(ctx, src, by_url[CAELYX])
    assert caelyx.title == "DHPC Caelyx" and caelyx.published == date(2026, 10, 30)
    assert caelyx.attachment_urls == ["https://www.cbg-meb.nl/site/binaries/site-content/collections/"
                                      "documents/2026/10/30/dhpc-caelyx/261030-dhpc-caelyx.pdf"]
    assert caelyx.body_text.startswith("De rubberen stop en aluminium afdichting")


# ─────────────────── Sweden: safety news with no category ───────────────────

def test_mpa_reads_safety_news_with_no_category():
    src = CFG["mpa-news"]
    assert src.options.get("all_safety_news") is True
    host = "https://www.lakemedelsverket.se"
    take = 40
    opts = {**src.options, "take": take}
    src = source("mpa-news", src.url, languages=["sv"], **opts)
    ctx = FakeCtx({lakemedelsverket.api_url(None, page_type=2, take=take): "mpa-news/api_safety_news_all.json",
                   host + "/api/newslist*": "mpa-news/api.json"})
    items = lakemedelsverket.list_items(ctx, src)
    titles = {i.title: i for i in items}
    ontozry = titles["Nya krav på kontroll av leverprover vid behandling med Ontozry"]
    assert ontozry.structured["categories"] == ["Säkerhetsnyhet"] and ontozry.doc_type == "safety_alert"
    category_titles = {r["heading"] for r in json.loads(fetched("mpa-news/api.json").content)["items"]}
    veterinary = {r["heading"] for r in json.loads(fetched("mpa-news/api_safety_news_all.json").content)["items"]
                  if "Läkemedel för djur" in r["categories"]}
    assert veterinary and not (veterinary - category_titles) & set(titles)
    assert lakemedelsverket.doc_type_for(["Säkerhetsnyhet", "Bristsituation"]) == "other"


def test_every_dhpc_list_found_is_read():
    """The letters lists the audit found, one per regulator, all enabled."""
    expected = {"ema-dhpc", "bfarm-rhb", "pei-rhb", "basg-dhpc", "ansm-securite", "dkma-dhpc",
                "aemps-dhpc", "cbg-dhpc", "hpra-notices", "aifa-sicurezza", "mpa-news",
                "ima-dhpc", "noma-dhpc", "lu-dhpc", "swissmedic-hpc", "medsafe-dhcp", "mfds-letters",
                "pmda-urgent", "pmda-company-letters", "hsa-announcements", "hc-recalls", "mhra-alerts"}
    assert expected <= {s.id for s in SOURCES if s.enabled}
    assert source("x", "https://example.invalid/").enabled            # the helper still builds


# ─────────────────── EU signals: the PRAC signal recommendations are read ───────────────────

def test_prac_signals_are_switched_on():
    from pathlib import Path

    assert CFG["ema-prac"].enabled and CFG["ema-prac"].parser == "prac"
    # The catalogue's flag only applies to a new row: the row already in the database is switched on
    # by a migration.
    sql = (Path(__file__).resolve().parent.parent / "supabase/migrations/0021_prac_signals_on.sql").read_text(
        encoding="utf-8")
    assert "update source set enabled = true" in sql and "id = 'ema-prac'" in sql
