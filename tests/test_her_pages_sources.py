"""Dr Sama's pages that no source read until 6 Nov 2026: EMA's news, Swissmedic's "New on this website",
Medsafe's Prescriber Update, the ministry's announcements on PMDA, and every circular on Infarmed's
circulars page. Each source is taken from the catalogue (collectors/sources.yaml) as it runs; every
fixture is the live page saved on 6 Nov 2026. Titles are asserted exactly as published."""

from __future__ import annotations

from datetime import date

import pytest

from collectors.core.registry import load_catalogue
from collectors.parsers import generic_html, infarmed, medsafe, pmda, swissmedic
from collectors.parsers.base import ParseError
from tests.fakes_a2 import FakeCtx, fixture, source

_, SOURCES, _ = load_catalogue()
CATALOGUE = {s.id: s for s in SOURCES}


def test_the_new_sources_are_switched_on_and_open_human_pages():
    for sid in ("ema-news", "swissmedic-updates", "medsafe-prescriber-update", "pmda-mhlw"):
        src = CATALOGUE[sid]
        assert src.enabled and src.kind == "safety" and src.channel == "html", sid
        assert src.page_url and src.page_url.startswith("https://"), sid
    assert CATALOGUE["ema-news"].regulator_id == "EMA"
    assert CATALOGUE["swissmedic-updates"].regulator_id == "SWISSMEDIC"
    assert CATALOGUE["medsafe-prescriber-update"].regulator_id == "MEDSAFE"
    assert CATALOGUE["pmda-mhlw"].regulator_id == "PMDA"


# ───────────────────────────── EMA ─────────────────────────────

EMA_NEWS = "https://www.ema.europa.eu/en/news"
GLP1 = EMA_NEWS + "/new-oral-glp-1-medicine-weight-management-type-2-diabetes"


def test_ema_news_reads_every_item_of_the_news_list():
    src = CATALOGUE["ema-news"]
    items = generic_html.list_items(FakeCtx({EMA_NEWS: "ema-news/list.html"}), src)
    assert len(items) == 10 and len({i.external_id for i in items}) == 10
    assert all(i.published and i.lang == "en" for i in items)
    # news.xml (seven items) had missed this one
    glp1 = next(i for i in items if i.url == GLP1)
    assert glp1.title == "New oral GLP-1 medicine for weight management and type 2 diabetes"
    assert glp1.published == date(2026, 10, 16) and glp1.doc_type == "other"
    assert glp1.structured["tag"] == "News, Human, Medicines"
    assert glp1.structured["summary"] == "Once-daily tablet provides an alternative to other oral and injectable GLP-1 medicines"
    prac = items[0]
    assert prac.title == ("Meeting highlights from the Pharmacovigilance Risk Assessment Committee (PRAC) "
                          "26 - 29 October 2026")
    assert prac.published == date(2026, 10, 30) and prac.doc_type == "safety_update"
    assert [i.doc_type for i in items].count("safety_update") == 2      # the two PRAC meetings only


def test_ema_news_detail_reads_the_article():
    src = CATALOGUE["ema-news"]
    ctx = FakeCtx({EMA_NEWS: "ema-news/list.html", GLP1: "ema-news/detail.html"})
    item = next(i for i in generic_html.list_items(ctx, src) if i.url == GLP1)
    item = generic_html.fetch_detail(ctx, src, item)
    assert "orforglipron" in item.body_text
    assert len(item.body_text) > 3000


def test_ema_news_changed_page_raises():
    with pytest.raises(ParseError):
        generic_html.list_items(FakeCtx({EMA_NEWS: "who-alerts/list.html"}), CATALOGUE["ema-news"])


# ───────────────────────────── Swissmedic ─────────────────────────────

SM_UPDATES = "https://www.swissmedic.ch/swissmedic/en/home/news/updates.html"
JOURNAL = "https://www.swissmedic.ch/swissmedic/en/home/about-us/publications/swissmedic-journal.html"


def test_swissmedic_updates_keep_everything_swissmedic_posts():
    src = CATALOGUE["swissmedic-updates"]
    assert src.url == SM_UPDATES and src.page_url == SM_UPDATES
    items = swissmedic.list_items(FakeCtx({SM_UPDATES: "swissmedic-updates/list.html"}), src)
    assert len(items) == 40 and len({i.external_id for i in items}) == 40
    assert all(i.lang == "en" and i.published for i in items)
    journal = items[0]
    assert journal.title == "Swissmedic Journal" and journal.url == JOURNAL
    assert journal.published == date(2026, 11, 5) and journal.doc_type == "newsletter"
    assert journal.external_id == JOURNAL + "@2026-11-05"
    by_title = {i.title: i for i in items}
    assert by_title["DHPC – Respreeza (alpha-1-proteinasi inhibitor humanum)"].doc_type == "dhpc"
    assert by_title["Wichtige Information von Swissmedic"].doc_type == "safety_update"
    assert by_title["Batch recall – Elocom, Lösung zur Anwendung auf der Haut"].doc_type == "recall"
    assert by_title["Eye disorders during amiodarone treatment"].doc_type == "newsletter"
    assert by_title["Save the Date: Clinical Trials Symposium 2027"].doc_type == "other"


def test_swissmedic_journal_next_month_is_a_new_item():
    # The Journal teaser links the same page every month: the date keeps each edition apart.
    src = CATALOGUE["swissmedic-updates"]
    page = fixture("swissmedic-updates/list.html").replace(b"05.11.2026", b"03.12.2026", 1)
    items = swissmedic.parse_list(page, SM_UPDATES, src, "en")
    assert items[0].url == JOURNAL and items[0].external_id == JOURNAL + "@2026-12-03"


def test_swissmedic_hpc_ids_are_unchanged():
    url = ("https://www.swissmedic.ch/swissmedic/de/home/humanarzneimittel/marktueberwachung/"
           "health-professional-communication--hpc-.html")
    items = swissmedic.parse_list(fixture("swissmedic-hpc/list_de.html"), url,
                                  source("swissmedic-hpc", url, languages=["de"]), "de")
    assert all(i.external_id == i.url for i in items)


# ───────────────────────────── Medsafe ─────────────────────────────

PU = "https://www.medsafe.govt.nz/profs/PUArticles.asp"
ROSU = "https://www.medsafe.govt.nz/profs/PUArticles/September2026/Rosuvastatin-dose-considerations.html"
ISSUE = "https://www.medsafe.govt.nz/profs/PUArticles/PDF/Prescriber-Update-47-No.3-September-2026.pdf"


def test_medsafe_prescriber_update_latest_issue():
    src = CATALOGUE["medsafe-prescriber-update"]
    assert medsafe.page_kind(src) == "prescriber"
    assert src.page_url == "https://www.medsafe.govt.nz/publications/prescriber-update.asp"
    items = medsafe.list_items(FakeCtx({PU: "medsafe-prescriber-update/list.html"}), src)
    assert len(items) == 11 and len({i.external_id for i in items}) == 11   # ten articles and the issue
    assert all(i.doc_type == "newsletter" and i.published == date(2026, 9, 3) for i in items)
    rosu = next(i for i in items if i.url == ROSU)
    assert rosu.title == "Rosuvastatin: Dose considerations"
    assert items[0].title == ("Spotlight on cystic fibrosis transmembrane conductance regulator (CFTR) "
                              "modulators")
    issue = items[-1]
    assert issue.title == "Prescriber Update – September 2026"
    assert issue.url == ISSUE and issue.attachment_urls == [ISSUE]
    assert "Rosuvastatin: Dose considerations" in issue.body_text


def test_medsafe_prescriber_revised_in_a_later_month_dates_the_issue_on_its_first_day():
    src = CATALOGUE["medsafe-prescriber-update"]
    page = fixture("medsafe-prescriber-update/list.html").replace(
        b"Revised: 3 September 2026", b"Revised: 2 October 2026")
    items = medsafe.parse_prescriber(page, PU, src)
    assert {i.published for i in items} == {date(2026, 9, 1)}


def test_medsafe_prescriber_article_takes_the_date_on_its_own_page():
    src = CATALOGUE["medsafe-prescriber-update"]
    ctx = FakeCtx({PU: "medsafe-prescriber-update/list.html", ROSU: "medsafe-prescriber-update/article.html"})
    item = next(i for i in medsafe.list_items(ctx, src) if i.url == ROSU)
    item.published = None
    item = medsafe.fetch_detail(ctx, src, item)
    assert item.published == date(2026, 9, 3)
    assert "rhabdomyolysis" in item.body_text


@pytest.mark.parametrize("other", ["medsafe-dhcp/list.html", "who-alerts/list.html"])
def test_medsafe_prescriber_changed_page_raises(other):
    with pytest.raises(ParseError):
        medsafe.list_items(FakeCtx({PU: other}), CATALOGUE["medsafe-prescriber-update"])


# ───────────────────────────── PMDA ─────────────────────────────

MHLW = "https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/mhlw-released/0001.html"


def test_pmda_mhlw_announcements():
    src = CATALOGUE["pmda-mhlw"]
    assert pmda.page_kind(src) == "mhlw" and src.expected_max_gap_days is None
    items = pmda.list_items(FakeCtx({MHLW: "pmda-mhlw/list.html"}), src)
    assert len(items) == 75 and len({i.external_id for i in items}) == 75
    assert all(i.published and i.lang == "ja" for i in items)
    first = items[0]
    assert first.title == "抗悪性腫瘍剤タゼメトスタット臭化水素酸塩の販売中止について"
    assert first.published == date(2026, 3, 27) and first.doc_type == "safety_alert"
    assert first.external_id == "pmda-mhlw:000279924"
    assert first.url == "https://www.pmda.go.jp/files/000279924.pdf"
    assert items[1].title == "医薬品自主回収のお知らせ（クラスI）（販売名：イトラコナゾール錠50「MEEK」）"
    assert items[1].doc_type == "recall" and items[1].published == date(2020, 12, 4)
    metformin = items[2]
    assert metformin.attachment_urls == ["https://www.pmda.go.jp/files/000236709.pdf",
                                         "https://www.pmda.go.jp/files/000236711.pdf"]
    assert metformin.structured["annexes"] == ["https://www.pmda.go.jp/files/000236711.pdf"]


def test_pmda_mhlw_changed_page_raises():
    with pytest.raises(ParseError):
        pmda.list_items(FakeCtx({MHLW: "who-alerts/list.html"}), CATALOGUE["pmda-mhlw"])


# ───────────────────────────── Infarmed ─────────────────────────────

ALERTAS = "https://www.infarmed.pt/web/infarmed/alertas"


def test_infarmed_keeps_every_circular_of_her_circulars_page():
    src = CATALOGUE["infarmed-circulares"]
    assert src.options.get("circulares_all") is True
    ctx = FakeCtx({ALERTAS: "infarmed-circulares/alertas.html",
                   infarmed.CIRCULARES: "infarmed-circulares/circulares.html"})
    items = infarmed.list_items(ctx, src)
    circulars = [i for i in items if i.external_id.startswith("infarmed:doc:")]
    titles = [i.title for i in circulars]
    assert len(circulars) == 19          # the twenty of the page; the iron circular is an Alertas notice
    nolotil = next(i for i in circulars if i.title == "Nolotil")
    assert nolotil.doc_type == "other" and nolotil.published == date(2026, 10, 16)
    assert any(t.startswith("Tavneos (avacopano) - recomendação de revogação") for t in titles)
    assert any(t.startswith("Sistema de Preços de Refêrencia") for t in titles)
    # the iron circular, posted without its number, is Alertas' circular 088 of the same day: kept once
    assert sum("compostos de ferro" in i.title for i in items) == 1
    keys = [k for k in (infarmed.circular_key(i.body_text or "") for i in items) if k]
    assert len(keys) == len(set(keys))
    steri = next(i for i in circulars if "Sterisets" in i.title)
    assert steri.doc_type == "recall"


def test_infarmed_without_the_option_still_keeps_alerts_only():
    src = source("infarmed-circulares", ALERTAS, languages=["pt"])
    items = infarmed.parse_circulares(fixture("infarmed-circulares/circulares.html"), infarmed.CIRCULARES, src)
    assert not any(i.title == "Nolotil" for i in items)
    assert all(i.doc_type == "recall" or "550.20.001" in (i.body_text or "") for i in items)
