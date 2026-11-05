"""PHAROS — A2 HTML / JSON / browser / e-mail parsers against the real fixtures (tests/fixtures/).

Every fixture was saved from the regulator's live site on 4 Nov 2026. Titles are asserted exactly
as published, in the regulator's own language.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from collectors.parsers import (aifa, ansm, bfarm_risk, cbg, dkma, email_inbox, famhp,
                                generic_html, hpra, ima_is, infarmed, lakemedelsverket, lu_sante,
                                medsafe, mfds, noma, pmda, prac, swissmedic, tga, who_alerts)
from collectors.core.models import Fetched, Item
from collectors.parsers._html_util import local_date
from collectors.parsers.base import FetchError, NotSetUp, ParseError, SourceBlocked
from tests.fakes_a2 import FakeCtx, fetched, fixture, source

# ───────────────────────────── dates ─────────────────────────────


@pytest.mark.parametrize("text,lang,expected", [
    ("PUBLIÉ LE 04/11/2026", "fr", date(2026, 11, 4)),
    ("02.november 2026", "da", date(2026, 11, 2)),
    (" 8. oktober 2026", "da", date(2026, 10, 8)),
    ("Oktober 2026", "nb", date(2026, 10, 1)),
    ("Október 2026", "is", date(2026, 10, 1)),
    ("Ágúst 2026", "is", date(2026, 8, 1)),
    ("29 September 2026", "en", date(2026, 9, 29)),
    ("October 27, 2026", "en", date(2026, 10, 27)),
    ("Nov-2026", "en", date(2026, 11, 1)),
    ("Jan - 2026", "en", date(2026, 1, 1)),
    ("05/2026", "ar", date(2026, 5, 1)),
    ("2026年10月27日", "ja", date(2026, 10, 27)),
    ("2026年4月", "ja", date(2026, 4, 1)),
    ("2026-05-21", "ko", date(2026, 5, 21)),
    ("30.10.2026", "de", date(2026, 10, 30)),
    ("no date here", "en", None),
])
def test_local_date(text, lang, expected):
    assert local_date(text, lang) == expected


# ───────────────────────────── France ─────────────────────────────

ANSM = "https://ansm.sante.fr/informations-de-securite/"


def test_ansm_list():
    src = source("ansm-securite", ANSM, languages=["fr"])
    items = ansm.parse_list(fixture("ansm-securite/list.html"), ANSM, src)
    assert len(items) == 20
    first, second = items[0], items[1]
    assert first.title == ("LAP : logiciel d'aide à la prescription – Easily-LAPCMP – "
                           "Hospices Civils de Lyon")
    assert first.published == date(2026, 11, 4)
    assert first.doc_type == "safety_update"           # INFORMATION AUX UTILISATEURS
    assert first.url.startswith("https://ansm.sante.fr/informations-de-securite/lap-")
    assert second.doc_type == "recall"                 # RAPPEL DE PRODUIT
    assert all(i.lang == "fr" for i in items)


def test_ansm_catalogue_reads_medicines_only():
    # Audit: the catalogue URL had no medicines filter, so devices and diagnostics came in.
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    url = next(s for s in sources if s.id == "ansm-securite").url
    assert url == ANSM + "?safety_news_filter[healthProducts][]=20"
    assert ansm._page_url(url, 2) == url + "&page=2"
    src = source("ansm-securite", url, languages=["fr"])
    items = ansm.parse_list(fixture("ansm-securite/list_medicaments.html"), url, src)
    assert len(items) == 20 and {i.structured["health_product"] for i in items} == {"Médicaments"}


def test_ansm_category_filter():
    src = source("ansm-securite", ANSM, languages=["fr"], include_categories=["RAPPEL DE PRODUIT"])
    items = ansm.parse_list(fixture("ansm-securite/list.html"), ANSM, src)
    assert items and all(i.structured["category"] == "RAPPEL DE PRODUIT" for i in items)


def test_ansm_detail_finds_the_letter():
    src = source("ansm-securite", ANSM, languages=["fr"])
    url = "https://ansm.sante.fr/informations-de-securite/ocrevus"
    ctx = FakeCtx({url: "ansm-securite/detail.html"})
    item = ansm.parse_list(fixture("ansm-securite/list.html"), ANSM, src)[0]
    item.url = url
    item = ansm.fetch_detail(ctx, src, item)
    assert item.attachment_urls == [
        "https://ansm.sante.fr/uploads/2026/10/08/2026108-dhpc-ocrevus.pdf"]
    assert item.body_text


def test_ansm_changed_page_raises():
    src = source("ansm-securite", ANSM, languages=["fr"])
    ctx = FakeCtx({ANSM: "who-alerts/list.html"})
    with pytest.raises(ParseError):
        ansm.list_items(ctx, src)


# ───────────────────────────── Italy ─────────────────────────────

AIFA = "https://www.aifa.gov.it/ricerca-aifa?searchKeywords=&structures=93604&adtCategories=1960204"


def test_aifa_niis():
    src = source("aifa-sicurezza", AIFA, languages=["it"])
    items = aifa.parse_list(fixture("aifa-sicurezza/niis_all.html"), AIFA, src)
    assert len(items) == 25
    oc = next(i for i in items if "Ocrevus" in i.title)
    assert oc.title == "Nota Informativa Importante di Sicurezza (NIIS) su Ocrevus (ocrelizumab)"
    assert oc.published == date(2026, 10, 8)
    assert oc.doc_type == "dhpc"
    assert oc.url == "https://www.aifa.gov.it/-/nota-informativa-importante-di-sicurezza-niis-ocrevus-ocrelizumab"
    assert oc.external_id.startswith("aifa:")
    assert oc.body_text.startswith("Ocrevus (ocrelizumab): nuovo rischio di danno epatico")


def test_aifa_live_page_with_java_dates():
    # The page a plain request gets (5 Nov 2026): dates written "Thu Oct 08 00:00:00 CEST 2026".
    src = source("aifa-sicurezza", AIFA, languages=["it"])
    items = aifa.parse_list(fixture("aifa-sicurezza/niis_live_2026-11-05.html"), AIFA, src)
    assert len(items) == 25
    oc = next(i for i in items if "Ocrevus" in i.title)
    assert oc.published == date(2026, 10, 8)
    assert oc.structured["category"] == "Sicurezza dei farmaci"
    assert all(i.published for i in items)


AIFA_COMMS = "https://www.aifa.gov.it/ricerca-aifa?searchKeywords=&structures=93604&adtCategories=1960205"


def test_aifa_communications_are_safety_updates_and_niis_stay_dhpc():
    # The second list holds AIFA/EMA communications; every one was typed DHPC (5 Nov 2026).
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    src = next(s for s in sources if s.id == "aifa-sicurezza")
    ctx = FakeCtx({AIFA: "aifa-sicurezza/niis_live_2026-11-05.html",
                   AIFA_COMMS: "aifa-sicurezza/comunicazioni_live_2026-11-05.html"})
    items = aifa.list_items(ctx, src)
    niis = [i for i in items if i.title.casefold().startswith("nota informativa importante")]
    comms = [i for i in items if i not in niis]
    assert len(niis) >= 25 and len(comms) >= 10
    assert {i.doc_type for i in niis} == {"dhpc"}
    assert {i.doc_type for i in comms} == {"safety_update"}
    assert any("paracetamolo" in i.title for i in comms)


def test_aifa_catalogue_points_at_the_niis_list():
    # It pointed at the landing page /sicurezza-dei-farmaci, which has no list: 3 failed runs.
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    assert next(s for s in sources if s.id == "aifa-sicurezza").url == AIFA


# ───────────────────────────── Ireland ─────────────────────────────

def test_hpra_api_keeps_human_medicines_only():
    src = source("hpra-notices", "https://www.hpra.ie/safety-information/safety-notices")
    items = hpra.parse_rows(json.loads(fixture("hpra-notices/api.json")), src)
    assert len(items) == 30                     # 20 of 50 rows are devices, vet or cosmetics
    first, second = items[0], items[1]
    assert first.title == "PRAC meeting highlights 26 - 29 October 2026"
    assert first.doc_type == "safety_update"
    assert second.title.startswith("PEDMARQSI (sodium thiosulfate) 80 mg/mL solution for infusion")
    assert second.doc_type == "dhpc"
    assert second.published == date(2026, 10, 30)
    assert second.url.startswith("https://www.hpra.ie/safety-information/safety-notices/article/pedmarqsi-")


def test_hpra_bad_answer_raises():
    src = source("hpra-notices", "https://www.hpra.ie/x")
    with pytest.raises(ParseError):
        hpra.parse_rows({"error": "x"}, src)


# ───────────────────────────── Nordics ─────────────────────────────

DKMA = "https://laegemiddelstyrelsen.dk/da/bivirkninger/direkte-sikkerhedsinformation/udsendte-meddelelser/"


def test_dkma_letters_link_the_pdf():
    src = source("dkma-dhpc", DKMA, languages=["da"])
    items = dkma.parse_list(fixture("dkma-dhpc/list.html"), DKMA, src)
    assert len(items) > 100
    first, second = items[0], items[1]
    assert first.title == "Oraqix Periodontal Gel"
    assert first.published == date(2026, 11, 2)
    # the page links "~/media/…"; the site serves the same PDF at /media/… (checked live, 200 application/pdf)
    assert first.url == "https://laegemiddelstyrelsen.dk/media/3B4CB26A8CA64DF5B0EE0163A527F07E.ashx"
    assert first.attachment_urls == [first.url]
    assert first.external_id == "dkma:3B4CB26A8CA64DF5B0EE0163A527F07E"
    assert second.title == "Ocrevus (ocrelizumab)"
    assert second.published == date(2026, 10, 8)
    assert len({i.external_id for i in items}) == len(items)


NOMA = ("https://www.dmp.no/bivirkninger-og-sikkerhet/tiltak-for-a-forebygge-bivirkninger/"
        "sikkerhetsinformasjon-til-helsepersonell-og-pasient/kjere-helsepersonell-brev")


def test_noma_letters():
    src = source("noma-dhpc", NOMA, languages=["nb"])
    items = noma.parse_list(fixture("noma-dhpc/list.html"), NOMA, src, years=1)
    assert items
    first = items[0]
    assert first.title.startswith("Bruk av Ocrevus (okrelizumab) gi leverskade.")
    assert first.structured["substance"] == "okrelizumab"
    assert first.structured["product"] == "Ocrevus"
    assert first.published == date(2026, 10, 1)
    assert first.url.startswith("https://www.dmp.no/globalassets/documents/")
    assert first.url.endswith(".pdf")
    assert all(i.published is None or i.published.year == 2026 for i in items)


IMA = "https://www.lyfjastofnun.is/lyf/lyfjagat/bref-til-heilbrigdisstarfsmanna-dhpc/"


def test_ima_icelandic_months():
    src = source("ima-dhpc", IMA, languages=["is"])
    items = ima_is.parse_list(fixture("ima-dhpc/list.html"), IMA, src)
    first, second = items[0], items[1]
    assert first.title == "Ocrevus"
    assert first.published == date(2026, 10, 1)
    assert first.url.endswith("/2026/10/20260930-ocrevus-dhpc-ima-signed.pdf")
    assert second.title == "Litfulo"
    assert second.published == date(2026, 8, 1)
    assert "Ritlecinib" in second.body_text


MPA_HOST = "https://www.lakemedelsverket.se"


def test_mpa_newslist():
    src = source("mpa-news", MPA_HOST + "/sv/nyheter", languages=["sv"])
    items = lakemedelsverket.parse_newslist(json.loads(fixture("mpa-news/api.json")), src)
    assert len(items) == 19
    first = items[0]
    assert first.title == ("Ocrevus (ocrelizumab): Risk för leverskada – nya rekommendationer om "
                           "övervakning av leverfunktionen")
    assert first.doc_type == "dhpc"
    assert first.published == date(2026, 10, 8)
    assert first.external_id == "mpa:78067"
    assert first.url.startswith(MPA_HOST + "/sv/nyheter/ocrevus-ocrelizumab-risk-for-leverskada")
    assert first.body_text == "Information till hälso- och sjukvården – DHPC."


def test_mpa_published_is_the_day_in_sweden():
    d = lakemedelsverket.published_date
    assert d("2026-03-04T23:30:00Z", "sv") == date(2026, 3, 5)        # 00:30 in Stockholm (UTC+1)
    assert d("2026-07-04T22:30:00+00:00", "sv") == date(2026, 7, 5)   # 00:30 in Stockholm (UTC+2)
    assert d("2025-06-04T05:22:30+00:00", "sv") == date(2025, 6, 4)
    assert d("2026-03-04", "sv") == date(2026, 3, 4)
    assert d(None, "sv") is None
    assert d("soon", "sv") is None


def test_mpa_content_api_body():
    text, pdfs = lakemedelsverket.parse_content(json.loads(fixture("mpa-news/detail_content.json")))
    assert "Sammanfattning" in text
    assert all(p.startswith(MPA_HOST) and p.lower().endswith(".pdf") for p in pdfs)


def test_mpa_list_sends_swedish_header():
    src = source("mpa-news", MPA_HOST, languages=["sv"], category_ids=[225])
    ctx = FakeCtx({MPA_HOST + "/api/newslist*": "mpa-news/api.json"})
    items = lakemedelsverket.list_items(ctx, src)
    assert len(items) == 19
    assert ctx.requests[0][2] == {"Accept-Language": "sv"}
    assert "categoryIds=225" in ctx.requests[0][1]


# ───────────────────────────── Portugal, Luxembourg ─────────────────────────────

INFARMED = "https://www.infarmed.pt/web/infarmed/alertas"


def test_infarmed_alerts():
    src = source("infarmed-circulares", INFARMED, languages=["pt"])
    items = infarmed.parse_list(fixture("infarmed-circulares/alertas.html"), INFARMED, src)
    assert items
    assert all(i.structured["family"] == "Medicamento de uso humano" for i in items)
    iron = items[0]
    assert iron.title.startswith("Medicamentos contendo compostos de ferro para administração intravenosa")
    assert iron.published == date(2026, 9, 4)
    assert iron.structured["circular"] == "088/CD/550.20.001"
    assert iron.external_id == "infarmed:13521417"
    salofalk = next(i for i in items if i.title.startswith("Recolha do medicamento Salofalk"))
    assert salofalk.doc_type == "recall"
    assert salofalk.published == date(2026, 8, 28)


def test_infarmed_detail_pdf():
    src = source("infarmed-circulares", INFARMED, languages=["pt"])
    url = INFARMED + "/-/journal_content/56/15786/13517026"
    ctx = FakeCtx({url: "infarmed-circulares/detail.html"})
    item = infarmed.parse_list(fixture("infarmed-circulares/alertas.html"), INFARMED, src)[0]
    item.url = url
    item = infarmed.fetch_detail(ctx, src, item)
    assert any(u.startswith("https://extranet.infarmed.pt/") for u in item.attachment_urls)


LU = ("https://santesecu.public.lu/fr/espace-professionnel/departement-sante/pharmacies-et-"
      "medicaments/pharmacovigilance/gestion-riques/dhcp.html")


def test_luxembourg_titles_without_size_marker():
    src = source("lu-dhpc", LU, languages=["fr"])
    items = lu_sante.parse_list(fixture("lu-dhpc/list.html"), LU, src)
    first, second = items[0], items[1]
    assert first.title.startswith("Ocrevus (ocrelizumab): Nouveau risque de lésion hépatique")
    assert "(Pdf" not in first.title and "|" not in first.title
    assert first.published == date(2026, 10, 8)
    assert first.url == ("https://santesecu.public.lu/dam-assets/fr/espace-professionnel/domaines/"
                         "dhpc/dhpc-2026/dhpc-ocrevus-lu-fr.pdf")
    assert first.doc_type == "dhpc"
    assert second.title.startswith("Brèves de pharmacovigilance - Retour PRAC 09 2026")
    assert second.doc_type == "safety_update"
    assert second.published == date(2026, 10, 2)


# ───────────────────────────── Switzerland, Germany ─────────────────────────────

SWISS_DE = ("https://www.swissmedic.ch/swissmedic/de/home/humanarzneimittel/marktueberwachung/"
            "health-professional-communication--hpc-.html")


def test_swissmedic_each_language_page():
    src = source("swissmedic-hpc", SWISS_DE, languages=["de", "fr", "it"])
    de = swissmedic.parse_list(fixture("swissmedic-hpc/list_de.html"), SWISS_DE, src, "de")
    assert len(de) == 12
    assert de[0].title == "DHPC – Respreeza (alpha-1-proteinasi inhibitor humanum)"
    assert de[0].doc_type == "dhpc"
    assert de[0].published == date(2026, 11, 4)
    assert de[0].lang == "de"
    for lang in ("fr", "it"):
        got = swissmedic.parse_list(fixture(f"swissmedic-hpc/list_{lang}.html"), SWISS_DE, src, lang)
        assert got and all(i.lang == lang for i in got)
    assert swissmedic.targets(src) == [("de", SWISS_DE)]


def test_swissmedic_detail_pdf():
    src = source("swissmedic-hpc", SWISS_DE, languages=["de"])
    item = swissmedic.parse_list(fixture("swissmedic-hpc/list_de.html"), SWISS_DE, src, "de")[0]
    ctx = FakeCtx({item.url: "swissmedic-hpc/detail_de.html"})
    item = swissmedic.fetch_detail(ctx, src, item)
    assert item.attachment_urls[0].endswith("/20261104-dhpc-respreeza_de.pdf")


BFARM = ("https://www.bfarm.de/DE/Arzneimittel/Pharmakovigilanz/Risikoinformationen/"
         "Risikobewertungsverfahren/_node.html")


def test_bfarm_risk_table():
    src = source("bfarm-risk", BFARM, languages=["de"])
    items = bfarm_risk.parse_list(fixture("bfarm-risk/list.html"), BFARM, src)
    first = items[0]
    assert first.title == "Deanxit (Flupentixol/Melitracen): Überprüfung des Nutzen-Risiko-Verhältnisses"
    assert first.published == date(2026, 10, 30)
    assert first.structured["wirkstoff"] == "Flupentixol/Melitracen"
    assert first.external_id == ("https://www.bfarm.de/SharedDocs/Risikoinformationen/"
                                 "Pharmakovigilanz/DE/RV_STP/a-f/flupentixol-melitracen.html")
    assert first.doc_type == "safety_update"
    assert first.structured["list"] == "Risikobewertungsverfahren"


BFARM_RI = "https://www.bfarm.de/DE/Arzneimittel/Pharmakovigilanz/Risikoinformationen/"


def test_bfarm_risk_catalogue_reads_the_three_german_lists():
    # It pointed at the English search page, which has no table: the parser found nothing there.
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    src = next(s for s in sources if s.id == "bfarm-risk")
    assert src.url == BFARM and src.languages == ["de"]
    assert src.options["extra_urls"] == [BFARM_RI + "Weitere-Arzneimittelrisiken/_node.html",
                                         BFARM_RI + "Aufforderung-zur-Textanpassung/_node.html"]
    ctx = FakeCtx({BFARM: "bfarm-risk/list.html",
                   src.options["extra_urls"][0]: "bfarm-risk/list_weitere_2026-11-05.html",
                   src.options["extra_urls"][1]: "bfarm-risk/list_textanpassung_2026-11-05.html"})
    items = bfarm_risk.list_items(ctx, src)
    lists = [i.structured["list"] for i in items]
    assert lists.count("Risikobewertungsverfahren") == 10
    assert lists.count("Weitere-Arzneimittelrisiken") == 15
    assert lists.count("Aufforderung-zur-Textanpassung") == 15
    assert all(i.lang == "de" and i.published for i in items)
    weitere = next(i for i in items if i.structured["list"] == "Weitere-Arzneimittelrisiken")
    assert weitere.doc_type == "safety_alert" and weitere.published == date(2026, 3, 18)
    assert weitere.structured["wirkstoff"] == "Colecalciferol, Vitamin D3, Fluorid"


def test_bfarm_risk_table_without_tbody():
    html = fixture("bfarm-risk/list.html").replace(b"<tbody>", b"").replace(b"</tbody>", b"")
    src = source("bfarm-risk", BFARM, languages=["de"])
    items = bfarm_risk.list_items(FakeCtx({BFARM: html}), src)
    assert len(items) == 10
    assert items[0].published == date(2026, 10, 30)


def test_national_language_pages_in_catalogue():
    # swissmedic-hpc read only /en/ and famhp-news only /en/news although the regulators publish
    # in de/fr/it and fr/nl: every regulator is screened in its own language.
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    by_id = {s.id: s for s in sources}
    swiss, famhp_src = by_id["swissmedic-hpc"], by_id["famhp-news"]
    assert [lang for lang, _ in swissmedic.targets(swiss)] == ["de", "fr", "it"]
    assert swiss.languages == ["de", "fr", "it"]
    assert all(f"/swissmedic/{lang}/" in url for lang, url in swissmedic.targets(swiss))
    assert famhp.targets(famhp_src) == [("fr", "https://www.afmps.be/fr/news"),
                                        ("nl", "https://www.fagg.be/nl/news")]
    assert famhp_src.languages == ["fr", "nl"]
    for src in (swiss, famhp_src):
        assert "/en/" not in src.url


# ───────────────────────────── New Zealand ─────────────────────────────

MEDSAFE = "https://www.medsafe.govt.nz/safety/"


def test_medsafe_dhcp_letters():
    src = source("medsafe-dhcp", MEDSAFE + "DHCPLetters.asp", page="dhcp")
    items = medsafe.parse_dhcp(fixture("medsafe-dhcp/list.html"), MEDSAFE + "DHCPLetters.asp", src)
    first = items[0]
    assert first.title == ("Zypine ODT (Olanzapine) 5 mg Orodispersible Tablets – Alternative "
                           "Registered Foils")
    assert first.published == date(2026, 9, 29)
    assert first.url == MEDSAFE + "DHCPLetters/ZypineODTSeptember2026.pdf"
    assert first.structured["product"] == "Zypine ODT"


def test_medsafe_comms_medicines_only():
    src = source("medsafe-comms", MEDSAFE + "SafetyCommunications.asp", page="comms")
    items = medsafe.parse_comms(fixture("medsafe-comms/list.html"),
                                MEDSAFE + "SafetyCommunications.asp", src)
    assert items[0].title == "The risks of unapproved peptide products"
    assert items[0].published == date(2026, 11, 4)
    assert items[0].doc_type == "safety_alert"
    assert all(i.structured["product_type"] == "Medicine" for i in items)
    assert not any("KayserBetten" in i.title for i in items)
    glp1 = next(i for i in items if "Glucagon-like peptide-1" in i.title)
    assert glp1.doc_type == "signal"                    # Monitoring communication


# ───────────────────────────── Japan, Korea ─────────────────────────────

PMDA_REV = ("https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/"
            "revision-of-precautions/")


def test_pmda_index_points_to_fiscal_year_pages():
    years = pmda.fiscal_year_links(fixture("pmda-revisions/index.html"), PMDA_REV + "0001.html")
    assert years[0] == (2026, PMDA_REV + "0375.html")
    assert years[1] == (2025, PMDA_REV + "0374.html")


def test_pmda_revisions_rowspans():
    src = source("pmda-revisions", PMDA_REV + "0001.html", languages=["ja"])
    items = pmda.parse_revisions(fixture("pmda-revisions/fy2026.html"), PMDA_REV + "0375.html", src)
    first = items[0]
    assert first.title == "インクリシランナトリウム"
    assert first.published == date(2026, 10, 27)
    assert first.url == "https://www.pmda.go.jp/files/000283216.pdf"
    assert first.external_id == "pmda-rev:000283216"
    assert "https://www.pmda.go.jp/files/000283214.pdf" in first.attachment_urls  # MHLW notice
    assert "https://www.pmda.go.jp/files/000283220.pdf" in first.attachment_urls  # report
    posa = next(i for i in items if i.title.startswith("ポサコナゾール"))
    assert posa.title == "ポサコナゾール（経口剤） / ポサコナゾール（注射剤）"
    assert posa.published == date(2026, 10, 8)
    assert "https://www.pmda.go.jp/files/000283150.pdf" in posa.attachment_urls  # shared report
    assert posa.structured["general_list"][0].endswith("/GeneralList/6179002")


def test_pmda_urgent_blue_letter():
    src = source("pmda-urgent", "https://www.pmda.go.jp/x/esc-rsc/0001.html", languages=["ja"])
    items = pmda.parse_urgent(fixture("pmda-urgent/list.html"), "https://www.pmda.go.jp/", src)
    first = items[0]
    assert first.title == "タブネオスカプセル10mgによる重篤な肝機能障害について"
    assert first.published == date(2026, 5, 21)
    assert first.structured["company"] == "キッセイ薬品工業株式会社"
    assert first.structured["letter_kind"] == "安全性速報"
    assert first.url == "https://www.pmda.go.jp/files/000280728.pdf"


def test_pmda_medical_safety_information():
    src = source("pmda-msi", "https://www.pmda.go.jp/x/0001.html", languages=["ja"])
    items = pmda.parse_msi(fixture("pmda-msi/list.html"), "https://www.pmda.go.jp/", src)
    first = items[0]
    assert first.title == ("インスリン専用注射器の使用について 投与量の誤りが重大な健康被害に"
                           "つながるおそれがあります")
    assert first.published == date(2026, 4, 1)
    assert first.external_id == "pmda-msi:73"


def test_pmda_page_kind_from_source_id():
    assert pmda.page_kind(source("pmda-urgent", "u")) == "urgent"
    assert pmda.page_kind(source("pmda-msi", "u")) == "msi"
    assert pmda.page_kind(source("pmda-revisions", "u")) == "revisions"


MFDS = "https://nedrug.mfds.go.kr/pbp/CCBAC01"


def test_mfds_letters():
    src = source("mfds-letters", MFDS, languages=["ko"])
    items = mfds.parse_list(fixture("mfds-letters/list.html"), MFDS, src)
    assert len(items) == 10
    first = items[0]
    assert first.title == "안전성속보 배포 알림"
    assert first.external_id == "mfds:516"
    assert first.published == date(2026, 5, 21)
    assert first.url == MFDS + "/getItem?safeLetterNo=516"
    assert first.body_text.startswith("미래바이오제약(주)에 대한 잠정 출하 중지")
    assert items[2].title == "의약품 정보 서한 배포 알림(설글리코타이드 제제)"
    assert items[2].doc_type == "dhpc"


def test_mfds_detail_attachment_download():
    body, urls, names = mfds.parse_detail(fixture("mfds-letters/detail.html"))
    assert "설글리코타이드" in body
    assert urls == ["https://nedrug.mfds.go.kr/cmn/edms/down/1PmiENXsZC6"]
    assert names and names[0].endswith(".pdf")


# ───────────────────────────── EMA PRAC, WHO ─────────────────────────────

PRAC = ("https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/"
        "pharmacovigilance-post-authorisation/signal-management/prac-recommendations-safety-signals")


def test_prac_signal_recommendations_with_translations():
    src = source("ema-prac", PRAC)
    items = prac.parse_signals(fixture("ema-prac/signals.html"), PRAC, src)
    first = items[0]
    assert first.title == ("PRAC recommendations on signals adopted at the 28 September-1 October "
                           "2026 PRAC meeting")
    assert first.external_id == "EMA/PRAC/206892/2026"
    assert first.published == date(2026, 10, 26)
    assert first.doc_type == "signal"
    assert first.url.endswith("-prac-meeting_en.pdf")
    assert first.attachment_urls == [first.url]
    # the recommendations are English only; the product-information wording beside them is in every EU language
    assert first.structured["translations"] is None
    wording = next(i for i in items if i.structured["translations"])
    assert "new-product-information-wording" in wording.url
    assert "bg" in wording.structured["translations"]


def test_prac_meeting_highlights():
    src = source("ema-prac", PRAC)
    items = prac.parse_highlights(fixture("ema-prac/committee_page.html"),
                                  "https://www.ema.europa.eu/en/committees/x", src)
    assert items
    assert all("highlight" in i.title.casefold() for i in items)
    assert all(i.url.startswith("https://www.ema.europa.eu/en/news/") for i in items)
    assert all(i.published is not None for i in items)


WHO = ("https://www.who.int/teams/regulation-prequalification/incidents-and-SF/"
       "full-list-of-who-medical-product-alerts")


def test_who_alerts():
    src = source("who-alerts", WHO)
    items = who_alerts.parse_list(fixture("who-alerts/list.html"), WHO, src)
    assert len(items) >= 10
    first = items[0]
    assert first.title == "Medical Product Alert N°3/2026: Falsified DARZALEX (daratumumab)"
    assert first.external_id == "who-mpa:2026-03"
    assert first.published == date(2026, 7, 3)
    assert len({i.external_id for i in items}) == len(items)


# ───────────────────────────── Arab regulators (generic_html presets) ─────────────────────────

EDA = "https://www.edaegypt.gov.eg/ar/"


def test_eda_dhpc_table():
    src = source("eda-eg", EDA, languages=["ar"])
    opts = generic_html.options_for(src)["pages"][0]
    items = generic_html.extract(fixture("eda-eg/dhpc.html"), EDA, src, opts)
    first = items[0]
    assert first.title.startswith("Evrysdi® (risdiplam) 0.75 mg/mL powder for oral solution")
    assert first.published == date(2026, 11, 1)                # "Nov-2026"
    assert first.doc_type == "dhpc"
    assert first.lang == "en"                                  # English row on an Arabic page
    assert first.url.startswith("https://www.edaegypt.gov.eg/media/") and first.url.endswith(".pdf")
    assert first.attachment_urls[0] == first.url


def test_eda_awareness_letters():
    src = source("eda-eg", EDA, languages=["ar"])
    opts = generic_html.options_for(src)["pages"][2]
    items = generic_html.extract(fixture("eda-eg/awareness_2026.html"), EDA, src, opts)
    first = items[0]
    assert first.title == "خطاب توعية رقم (1) لسنة 2026"
    assert first.lang == "ar"
    assert first.published == date(2026, 1, 1)
    assert first.body_text == "Lentris 10 mg"
    assert first.doc_type == "recall"


SFDA = "https://www.sfda.gov.sa/ar/warnings"


def test_sfda_warning_cards():
    src = source("sfda-sa", SFDA, languages=["ar"])
    opts = generic_html.options_for(src)["pages"][0]
    shape = {k: v for k, v in opts.items() if k != "include_tags"}
    items = generic_html.extract(fixture("sfda-sa/warnings.html"), SFDA, src, shape)
    first = items[0]
    assert first.title.startswith("\"الغذاء والدواء\" تحذّر من منتجات بروتين البودينغ")
    assert first.published == date(2026, 10, 27)
    assert first.external_id == "sfda-sa:19788"
    assert first.structured["tag"] == "غذاء"
    assert first.url == "https://www.sfda.gov.sa/ar/warnings/19788"


def test_sfda_warnings_keep_drug_cards_only():
    # Audit: the warnings list is mostly food; only cards tagged دواء (drug) are kept, also when a
    # card carries both tags (the drug tag second).
    src = source("sfda-sa", SFDA, languages=["ar"])
    opts = generic_html.options_for(src)["pages"][0]
    assert generic_html.extract(fixture("sfda-sa/warnings.html"), SFDA, src, opts) == []
    both = generic_html.extract(fixture("sfda-sa/warnings_drug.html"), SFDA, src, opts)
    assert [i.external_id for i in both] == ["sfda-sa:6491"]
    assert both[0].structured["tag"] == "غذاء, دواء"
    # an all-food page is not a broken page: the source still reads it without failing
    ctx = FakeCtx({SFDA: "sfda-sa/warnings.html",
                   "https://www.sfda.gov.sa/ar/drugs_circulars_withdrawal": "sfda-sa/drugs_circulars_withdrawal.html"})
    got = generic_html.list_items(ctx, src)
    assert got and all(i.doc_type == "recall" for i in got)


def test_sfda_recall_table():
    src = source("sfda-sa", SFDA, languages=["ar"])
    opts = generic_html.options_for(src)["pages"][1]
    items = generic_html.extract(fixture("sfda-sa/drugs_circulars_withdrawal.html"),
                                 "https://www.sfda.gov.sa/ar/drugs_circulars_withdrawal", src, opts)
    assert items and all(i.doc_type == "recall" for i in items)
    first = next(i for i in items if i.title == "منتجات شركة أستركس فارما الصناعية")
    assert first.published == date(2025, 6, 27)
    assert first.url == "https://www.sfda.gov.sa/ar/drugs_circulars_withdrawal/18835"


JFDA = "https://www.jfda.jo/AR/List/أحدث_التعاميم_الصادرة"


def test_jfda_circulars():
    src = source("jfda-jo", JFDA, languages=["ar"])
    items = generic_html.extract(fixture("jfda-jo/circulars.html"), JFDA, src,
                                 generic_html.options_for(src))
    first = items[0]
    assert first.title == "تعميم بخصوص المستلزمات الطبية المعقمة والتي تسجل"
    assert first.published == date(2026, 10, 29)
    assert first.url.startswith("https://www.jfda.jo/EBV4.0/Root_Storage/AR/EB_List_Page/")
    assert first.url.endswith(".pdf")


def test_generic_html_needs_a_selector():
    src = source("user-1", "https://example.invalid/")
    with pytest.raises(ParseError):
        generic_html.extract(b"<html><body><a href='/x'>x</a></body></html>", src.url, src, {})


def test_a_source_without_reading_rules_says_so_before_fetching():
    # Audit: uae-mohap has no preset; switched on it fetched the page, then failed as "the page changed shape".
    src = source("uae-mohap", "https://mohap.gov.ae/en/media-center/news", languages=["ar", "en"])
    ctx = FakeCtx({})
    with pytest.raises(NotSetUp, match="no reading rules yet"):
        generic_html.list_items(ctx, src)
    assert ctx.requests == []


def test_generic_html_year_template():
    assert generic_html._expand("https://x/{year}/", False)[0].startswith("https://x/20")
    assert len(generic_html._expand("https://x/{year}/", True)) == 2
    # January: the new year's page may not exist yet, so last year's is read too.
    assert generic_html._expand("https://x/{year}/", False, date(2027, 1, 3)) == ["https://x/2027/",
                                                                                "https://x/2026/"]
    assert generic_html._expand("https://x/{year}/", False, date(2027, 2, 1)) == ["https://x/2027/"]


def test_a_year_page_not_there_yet_does_not_fail_the_source():
    # Audit: in January the EDA awareness page for the new year answered 404 and failed eda-eg.
    year = date.today().year
    url = "https://x.invalid/letters/{year}/"
    opts = {"item_selector": "table tr", "title_selector": "td:nth-of-type(1) a",
            "date_selector": "td:nth-of-type(2)", "summary_selector": "td:nth-of-type(3)",
            "doc_type": "recall", "url": url}
    src = source("eda-eg", "https://x.invalid/", languages=["ar"])
    ctx = FakeCtx({url.format(year=year - 1): "eda-eg/awareness_2026.html"}, backfill=True)
    items = generic_html.list_with(ctx, src, opts)
    assert items and [r[1] for r in ctx.requests] == [url.format(year=year), url.format(year=year - 1)]
    with pytest.raises(FetchError):                      # neither year there: still a failure
        generic_html.list_with(FakeCtx({}, backfill=True), src, opts)


# ───────────────────────────── browser sources ─────────────────────────────

def test_famhp_interstitial_is_blocked_not_bypassed():
    f = fetched("famhp-news/challenge_fr.html", "https://www.afmps.be/fr/news")
    with pytest.raises(SourceBlocked):
        famhp.check_not_interstitial(f)


FAMHP_NEWS = {"fr": "https://www.afmps.be/fr/news/vitamine_d3_colecalciferol_attention_aux_differents_dosages",
              "nl": "https://www.fagg.be/nl/news/vitamine_d3_cholecalciferol_opgelet_met_verschillende_doseringen"}


@pytest.mark.parametrize("lang", ["fr", "nl"])
def test_famhp_news_date_comes_from_the_news_page(lang):
    # The lists show no dates (seen 5 Nov 2026); the page's publication-date field does, and the
    # "last updated" stamp below it (16/10/2026) is not the date of the news.
    src = source("famhp-news", "https://www.afmps.be/fr/news", languages=["fr", "nl"], parser="famhp")
    ctx = FakeCtx({FAMHP_NEWS[lang]: f"famhp-news/detail_{lang}.html"})
    item = Item(external_id=FAMHP_NEWS[lang], url=FAMHP_NEWS[lang], title="Vitamine D3", published=None,
                doc_type="other", lang=lang)
    item = famhp.fetch_detail(ctx, src, item)
    assert item.published == date(2026, 10, 15)
    assert "vitamine D3" in item.body_text


def test_famhp_a_date_from_the_list_is_kept():
    ctx = FakeCtx({FAMHP_NEWS["fr"]: "famhp-news/detail_fr.html"})
    src = source("famhp-news", "https://www.afmps.be/fr/news", languages=["fr", "nl"], parser="famhp")
    item = Item(external_id="x", url=FAMHP_NEWS["fr"], title="t", published=date(2026, 10, 14),
                doc_type="other", lang="fr")
    assert famhp.fetch_detail(ctx, src, item).published == date(2026, 10, 14)


F5_INJECTED = (b'<script type="text/javascript" '
               b'src="/TSPD/08e8b1e6a8ab2000c5d2e4b2f1a3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1?type=7">'
               b'</script>')


def test_famhp_normal_page_with_f5_script_is_not_blocked():
    # F5 injects its /TSPD/…?type=7 script into ordinary protected pages; only the interstitial's
    # own markers (href="/TSPD/?type=, window["bobcmn"]) mean a challenge.
    page = fixture("swissmedic-hpc/list_fr.html").replace(b"</head>", F5_INJECTED + b"</head>", 1)
    assert b"/TSPD/" in page
    famhp.check_not_interstitial(Fetched(200, "https://www.afmps.be/fr/news", page,
                                         "text/html; charset=utf-8"))


def _famhp_pages() -> dict:
    fr = ("<main><a href='/fr/news/securite-ibuprofene'>Sécurité : ibuprofène</a> 04/11/2026"
          "<a href='/fr/news/journee-portes-ouvertes'>Journée portes ouvertes</a> 03/11/2026</main>")
    nl = ("<main><a href='/nl/news/veiligheid-ibuprofen'>Veiligheid: ibuprofen</a> 04/11/2026"
          "<a href='/nl/news/opendeurdag'>Opendeurdag</a> 03/11/2026</main>")
    return {"https://www.afmps.be/fr/news": fr.encode(), "https://www.fagg.be/nl/news": nl.encode()}


def test_famhp_keywords_per_language(caplog):
    # Audit: one include list for the French and Dutch pages dropped the other language silently.
    urls = {"fr": "https://www.afmps.be/fr/news", "nl": "https://www.fagg.be/nl/news"}
    per_lang = source("famhp-news", urls["fr"], languages=["fr", "nl"], channel="browser", urls=urls,
                      include_keywords={"fr": ["sécurité"], "nl": ["veiligheid"]})
    items = famhp.list_items(FakeCtx(_famhp_pages()), per_lang)
    assert [(i.lang, i.title) for i in items] == [("fr", "Sécurité : ibuprofène"), ("nl", "Veiligheid: ibuprofen")]

    one_list = source("famhp-news", urls["fr"], languages=["fr", "nl"], channel="browser", urls=urls,
                      include_keywords=["sécurité"])
    with caplog.at_level("WARNING", logger="collectors.parsers.famhp"):
        items = famhp.list_items(FakeCtx(_famhp_pages()), one_list)
    assert [i.lang for i in items] == ["fr"]
    assert "famhp-news nl: 2 news link(s), none kept by the keyword filter" in caplog.text


def test_keep_reads_a_keyword_list_per_language():
    from collectors.parsers._html_util import keep

    src = source("x", "https://x.invalid/", include_keywords={"fr": ["rappel"], "nl": ["terugroeping"]},
                 exclude_keywords={"fr": ["vétérinaire"]})
    assert keep(src, "Rappel de lot", lang="fr") and not keep(src, "Rappel de lot", lang="nl")
    assert keep(src, "Terugroeping", lang="nl-BE")
    assert not keep(src, "Rappel vétérinaire", lang="fr")
    assert keep(src, "News", lang="de")            # a language with no list is not filtered
    assert not keep(source("y", "https://x.invalid/", include_keywords=["rappel"]), "News", lang="fr")


def test_famhp_reads_with_browser_and_stops_at_challenge():
    src = source("famhp-news", "https://www.afmps.be/fr/news", languages=["fr", "nl"],
                 channel="browser")
    ctx = FakeCtx({"https://www.afmps.be/fr/news": "famhp-news/challenge_fr.html"})
    with pytest.raises(SourceBlocked):
        famhp.list_items(ctx, src)
    assert ctx.requests[0][0] == "BROWSER"


def test_cbg_server_html_has_no_items_and_dates_come_from_path():
    src = source("cbg-news", "https://www.cbg-meb.nl/actueel/nieuws", languages=["nl"],
                 channel="browser")
    assert cbg.parse_rendered(fixture("cbg-news/list.html"),
                              "https://www.cbg-meb.nl/actueel/nieuws", src) == []
    assert cbg.date_from_path("https://www.cbg-meb.nl/actueel/nieuws/2026/10/30/x") == date(2026, 10, 30)


def test_tga_page_options():
    alerts = tga.options_for(source("tga-alerts", "https://www.tga.gov.au/safety/safety-alerts"))
    updates = tga.options_for(source("tga-updates", "https://www.tga.gov.au/news/safety-updates"))
    assert alerts["browser"] is True and alerts["doc_type"] == "safety_alert"
    assert "safety-alerts" in alerts["link_pattern"]
    assert updates["doc_type"] == "safety_update" and "safety-updates" in updates["link_pattern"]


# ───────────────────────────── e-mail ─────────────────────────────

def test_email_rows_to_items():
    src = source("fimea-email", "mailto:pharos@satopharma.com", languages=["fi"],
                 channel="email", web_domain="fimea.fi")
    rows = [{"id": "11111111-1111-1111-1111-111111111111", "received_at": "2026-11-03T08:00:00Z",
             "from_addr": "uutiskirje@fimea.fi", "subject": "Fimean tiedote: lääketurvallisuus",
             "r2_key": "inbound/2026-11-03/x.eml", "text_body": "Rivi 1\n\nRivi 2",
             "html_body": "<p><a href='https://fimea.fi/-/tiedote'>Lue lisää</a></p>",
             "processed_at": None}]
    items = email_inbox.items_from_rows(rows, src)
    assert len(items) == 1
    it = items[0]
    assert it.title == "Fimean tiedote: lääketurvallisuus"
    assert it.url == "https://fimea.fi/-/tiedote"
    assert it.published == date(2026, 11, 3)
    assert it.doc_type == "newsletter" and it.lang == "fi"
    assert it.body_text == "Rivi 1\nRivi 2"
    assert it.attachment_urls == []                    # links into a blocked site are not fetched


def test_email_split_links():
    src = source("tga-email", "mailto:x", channel="email", split_links=r"tga\.gov\.au/news/")
    rows = [{"id": "22222222-2222-2222-2222-222222222222", "received_at": "2026-11-02",
             "subject": "TGA safety updates", "text_body": "", "processed_at": None,
             "html_body": ("<a href='https://www.tga.gov.au/news/safety-alerts/a'>Alert A</a>"
                           "<a href='https://www.tga.gov.au/news/safety-alerts/b'>Alert B</a>"
                           "<a href='https://www.tga.gov.au/about'>About</a>")}]
    items = email_inbox.items_from_rows(rows, src)
    assert [i.title for i in items] == ["Alert A", "Alert B"]
    assert items[0].structured["subject"] == "TGA safety updates"


class _InboxDb:
    def __init__(self, rows):
        self.rows, self.marked = rows, []

    def fetchall(self, sql, params=None):
        return self.rows

    def execute(self, sql, params=None):
        assert sql.startswith("update inbound_email set processed_at")
        self.marked += params["ids"]


class _InboxCtx:
    def __init__(self, rows, dry_run=False):
        self.db, self.dry_run = _InboxDb(rows), dry_run


def test_email_rows_are_marked_only_once_their_items_are_stored():
    # Audit: rows were marked processed when read, so an item that then failed to store was lost.
    src = source("tga-email", "mailto:x", channel="email", split_links=r"tga\.gov\.au/news/",
                 include_keywords=["safety"])
    a, b, c = "aaaaaaaa-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002",         "cccccccc-0000-0000-0000-000000000003"
    digest = ("<a href='https://www.tga.gov.au/news/safety-alerts/a'>Safety alert A</a>"
              "<a href='https://www.tga.gov.au/news/safety-alerts/b'>Safety alert B</a>")
    rows = [{"id": a, "received_at": "2026-11-02", "subject": "safety digest", "text_body": "",
             "html_body": digest, "processed_at": None},
            {"id": b, "received_at": "2026-11-02", "subject": "Safety notice", "text_body": "one",
             "html_body": None, "processed_at": None},
            {"id": c, "received_at": "2026-11-02", "subject": "Event invitation", "text_body": "x",
             "html_body": None, "processed_at": None}]
    ctx = _InboxCtx(rows)
    items = email_inbox.list_items(ctx, src)
    assert ctx.db.marked == [c]                           # filtered out: nothing to store
    assert {i.external_id for i in items} == {"https://www.tga.gov.au/news/safety-alerts/a",
                                              "https://www.tga.gov.au/news/safety-alerts/b", f"email:{b}"}
    # alert B failed to store: the digest stays unprocessed and is read again
    email_inbox.after_store(ctx, src, items, {"https://www.tga.gov.au/news/safety-alerts/a", f"email:{b}"})
    assert ctx.db.marked == [c, b]

    dry = _InboxCtx(rows, dry_run=True)
    items = email_inbox.list_items(dry, src)
    email_inbox.after_store(dry, src, items, {i.external_id for i in items})
    assert dry.db.marked == []                            # a dry run never consumes the mailbox


def test_catalogue_channel_says_how_the_source_is_read():
    # Audit: mpa-news said "browser" but its parser calls a plain JSON API.
    import importlib
    import inspect

    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    for s in sources:
        if s.channel != "browser":
            continue
        try:
            module = importlib.import_module(f"collectors.parsers.{s.parser}")
        except ImportError:
            module = importlib.import_module(f"collectors.spc.{s.parser}")
        code = inspect.getsource(module)
        assert "browser" in code and ("browser_get" in code or (s.options or {}).get("browser")), s.id
    assert {s.id: s.channel for s in sources}["mpa-news"] == "api"


def test_catalogue_urls_match_the_pages_the_parsers_read():
    # Two catalogue entries pointed at landing pages with no list (both failed every run, 5 Nov 2026).
    from collectors.core.registry import load_catalogue

    _, sources, _ = load_catalogue()
    urls = {s.id: s.url for s in sources}
    assert urls["infarmed-circulares"] == "https://www.infarmed.pt/web/infarmed/alertas"
