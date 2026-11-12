"""Feed-like parsers against the real fixtures captured from each regulator (tests/fixtures/<source>/).

Options come from collectors/sources.yaml, so a change to a source's filters is tested here too.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from collectors.core.archive import Archive
from collectors.core.context import FetchContext, FetchError
from collectors.core.registry import load_catalogue
from collectors.parsers import govuk, hc_recalls, openfda_enforcement, pubmed
from collectors.parsers.base import ParseError
from collectors.parsers.feed import parse_feed

FIX = Path(__file__).resolve().parent / "fixtures"
_, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}
IRES = "https://www.accessdata.fda.gov/scripts/ires/index.cfm"


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


def test_jfda_news_keeps_medicine_items_only():
    # Google News, 13 Nov 2026: Jordan's regulator site is down, so its medicine news comes from here.
    # The authority's own name holds "Drug", so the bare word must never be a keyword: olive mills,
    # tobacco, nail polish and infant formula stories carry it too and have to be dropped.
    en = feed("jfda-news-en", "jfda-news/en.xml")
    assert len(en) == 11  # of 36 entries
    titles = " | ".join(i.title for i in en)
    for food in ("olive", "Tobacco", "Nail Polish", "Infant Formula", "Anti-Drug"):
        assert food not in titles
    zantac = next(i for i in en if "Zantac" in i.title)
    assert zantac.doc_type == "recall" and zantac.published == date(2019, 10, 19)
    assert next(i for i in en if "Diprofos" in i.title).doc_type == "recall"
    assert next(i for i in en if "leaflet" in i.title).doc_type == "label_change"
    assert all(i.lang == "en" and i.url.startswith("https://news.google.com/") for i in en)

    ar = feed("jfda-news-ar", "jfda-news/ar.xml")
    assert len(ar) == 7  # of 18 entries
    titles = " | ".join(i.title for i in ar)
    for food in ("حليب", "العسل", "غذائية"):  # baby milk, honey, food poisoning
        assert food not in titles
    assert any("الميزوثيرابي" in i.title for i in ar)  # injecting mesotherapy products banned
    assert next(i for i in ar if "شوائب" in i.title).doc_type == "recall"
    assert all(i.lang == "ar" for i in ar)


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
    assert first.url == f"{IRES}?Event=99849"            # FDA's own page for the recall's event
    assert "Reason for recall:" in first.body_text
    with pytest.raises(ParseError):
        openfda_enforcement.record_to_item({"product_description": "x"}, base)


def test_openfda_record_without_recall_number_is_kept():
    # A real record (event 100061) that openFDA publishes with recall_number "": it used to fail the
    # whole source ("record without recall_number"). It now gets a stable id from event id + product.
    rec = json.loads(fixture("fda-enforcement/blank-recall-number.json"))["results"][0]
    base = CFG["fda-enforcement"].url
    a = openfda_enforcement.record_to_item(rec, base)
    b = openfda_enforcement.record_to_item(dict(rec), base)
    assert a.external_id.startswith("event-100061-") and a.external_id == b.external_id
    assert a.url == f"{IRES}?Event=100061"
    assert a.title.startswith("Amitriptyline Hydrochloride")


def test_openfda_item_opens_fdas_enforcement_report_page():
    # Dr Sama's review, 6 Nov 2026: a recall's link opened raw JSON from api.fda.gov. FDA's Enforcement
    # Report opens one event's products from ?Event=<event id> (the share link its own page builds).
    data = json.loads(fixture("fda-enforcement/enforcement-limit5.json"))
    base = CFG["fda-enforcement"].url
    items = [openfda_enforcement.record_to_item(r, base) for r in data["results"]]
    assert [i.url for i in items[:2]] == [f"{IRES}?Event=99849", f"{IRES}?Event=100072"]
    assert not any("api.fda.gov" in i.url for i in items)
    # a record without an event id opens the Enforcement Report itself, never the API
    rec = dict(data["results"][0], event_id="")
    assert openfda_enforcement.record_to_item(rec, base).url == IRES


def openfda_ctx(tmp_path, answers: list[int]):
    """openFDA answering ``answers`` in turn (then 200 with the five saved records)."""
    calls: list[str] = []
    down = b'{"error": {"code": "SERVER_ERROR", "message": "Check your request and try again"}}'
    data = json.loads(fixture("fda-enforcement/enforcement-limit5.json"))
    data["meta"]["results"]["total"] = len(data["results"])     # one page
    page = json.dumps(data).encode()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        status = answers[len(calls) - 1] if len(calls) <= len(answers) else 200
        body = page if status == 200 else down
        return httpx.Response(status, headers={"content-type": "application/json"}, content=body)

    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    sleeps: list[float] = []
    ctx._sleep = sleeps.append
    return ctx, calls, sleeps


def test_openfda_server_error_is_asked_again(tmp_path):
    # 5 Nov 2026 21:17 Cairo: openFDA answered the backfill's first page with HTTP 500; the same query
    # answered 200 straight after.
    ctx, calls, sleeps = openfda_ctx(tmp_path, [500, 502])
    items = openfda_enforcement.list_items(ctx, CFG["fda-enforcement"])
    assert len(items) == 5 and len(calls) == 3 and sleeps == [15.0, 35.0]


def test_openfda_still_down_fails_with_its_own_message(tmp_path):
    ctx, calls, _ = openfda_ctx(tmp_path, [500, 500, 500])
    with pytest.raises(FetchError) as err:
        openfda_enforcement.list_items(ctx, CFG["fda-enforcement"])
    assert len(calls) == 3 and err.value.status == 500
    assert "openFDA: SERVER_ERROR Check your request and try again" in str(err.value)


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


NCBI_DOWN = (b'{"header":{"type":"esearch","version":"0.3"},"esearchresult":{"ERROR":"Search Backend '
             b'failed: Search is temporarily unavailable. Please try again later. Details: Cannot connect '
             b'to SOLR"}}')


def ncbi_ctx(tmp_path, esearch_failures: int, last_ok_at=None, backend_down: bool = False):
    """A context whose E-utilities fails the first ``esearch_failures`` searches: HTTP 500, or (as
    on 2026-11-05) HTTP 200 carrying "Search Backend failed"."""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "esearch" in req.url.path:
            if sum("esearch" in c for c in calls) <= esearch_failures:
                if backend_down:
                    return httpx.Response(200, headers={"content-type": "application/json"}, content=NCBI_DOWN)
                return httpx.Response(500, headers={"content-type": "text/html"}, text="<html>Error</html>")
            # PubMed's first page; PubMed Central, and every later page, have nothing more
            q = parse_qs(urlsplit(str(req.url)).query)
            first = q["db"] == ["pubmed"] and q["retstart"] == ["0"]
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  content=fixture("pubmed/esearch-lornoxicam.json" if first
                                                  else "pubmed/esearch-empty.json"))
        return httpx.Response(200, headers={"content-type": "application/json"},
                              content=fixture("pubmed/esummary.json"))

    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    sleeps: list[float] = []
    ctx._sleep = sleeps.append
    ctx.watchlist = ["lornoxicam"]
    ctx.last_ok_at = last_ok_at
    return ctx, calls, sleeps


def test_pubmed_esummary(tmp_path):
    search = json.loads(fixture("pubmed/esearch-lornoxicam.json"))
    assert search["esearchresult"]["idlist"]
    ctx, _, _ = ncbi_ctx(tmp_path, 0)
    items = pubmed.list_items(ctx, CFG["pubmed"])
    assert [i.external_id for i in items] == ["42846100", "42770875", "42859397"]
    first = items[0]
    assert first.url == "https://pubmed.ncbi.nlm.nih.gov/42846100/"
    assert first.doc_type == "literature"
    assert first.published == date(2026, 10, 7)          # sortpubdate 2026/10/07
    assert first.structured["query_term"] == ["lornoxicam"]
    assert first.structured["pmcid"] == "PMC13643229"    # its PubMed record names its full text
    assert first.structured["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13643229/"
    with pytest.raises(ParseError):
        pubmed.summaries({"error": "x"}, ["42846100"])


def mindate(calls: list[str]) -> date:
    q = parse_qs(urlsplit(next(c for c in calls if "esearch" in c)).query)
    return datetime.strptime(q["mindate"][0], "%Y/%m/%d").date()


def test_pubmed_waits_out_ncbi_server_errors(tmp_path):
    ctx, calls, sleeps = ncbi_ctx(tmp_path, esearch_failures=3)
    items = pubmed.list_items(ctx, CFG["pubmed"])
    assert [i.external_id for i in items] == ["42846100", "42770875", "42859397"]
    assert sleeps == [5.0, 15.0, 30.0]


def test_pubmed_fails_when_ncbi_stays_down(tmp_path):
    ctx, calls, sleeps = ncbi_ctx(tmp_path, esearch_failures=99)
    with pytest.raises(FetchError) as err:
        pubmed.list_items(ctx, CFG["pubmed"])
    assert err.value.status == 500
    assert sleeps == [5.0, 15.0, 30.0, 60.0] and len(calls) == 5


def test_pubmed_search_backend_down_is_waited_out_then_counts_as_down(tmp_path):
    ctx, _, sleeps = ncbi_ctx(tmp_path, esearch_failures=2, backend_down=True)
    assert len(pubmed.list_items(ctx, CFG["pubmed"])) == 3
    assert sleeps == [5.0, 15.0]
    ctx, calls, _ = ncbi_ctx(tmp_path, esearch_failures=99, backend_down=True)
    with pytest.raises(FetchError) as err:                    # a failure, never ParseError
        pubmed.list_items(ctx, CFG["pubmed"])
    assert err.value.status == 503 and "temporarily unavailable" in str(err.value)
    assert len(calls) == 5


def test_pubmed_searches_back_to_the_last_complete_run(tmp_path):
    today = date.today()
    ctx, calls, _ = ncbi_ctx(tmp_path, 0)                     # first run: the 10-day lookback
    pubmed.list_items(ctx, CFG["pubmed"])
    assert mindate(calls) == today - timedelta(days=10)
    missed = datetime.now(timezone.utc) - timedelta(days=17)  # two weekly runs failed
    ctx, calls, _ = ncbi_ctx(tmp_path, 0, last_ok_at=missed)
    pubmed.list_items(ctx, CFG["pubmed"])
    assert mindate(calls) == missed.date() - timedelta(days=3)
    ctx, calls, _ = ncbi_ctx(tmp_path, 0, last_ok_at=datetime.now(timezone.utc) - timedelta(days=400))
    pubmed.list_items(ctx, CFG["pubmed"])
    assert mindate(calls) == today - timedelta(days=90)
