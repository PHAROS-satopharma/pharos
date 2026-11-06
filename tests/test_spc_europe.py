"""The label watch in Europe: the Netherlands (CBG), Belgium (FAMHP), Italy (AIFA), Sweden (MPA), Portugal
(Infomed), Ireland (HPRA), Austria (BASG) and Iceland (Sérlyfjaskrá), read from answers saved on 6 and 7 Nov 2026
(tests/fixtures/spc-cbg … spc-lyfja; see their README files). No saved file holds a key: HPRA's page and BASG's
script are stood in for by a few lines carrying a made-up one."""

from __future__ import annotations

import json
from datetime import date

import pytest

from collectors.core.context import FetchError, ParseError, redact
from collectors.core.models import Fetched
from collectors.core.registry import load_catalogue
from collectors.spc import aifa, basg, cbg, famhp, hpra, infomed, lyfja, mpa, read_check, replay
from collectors.spc.common import label_date, label_revision
from collectors.spc.diff import diff_sections
from collectors.spc.run import MODULES
from collectors.spc.sections import eu_label_sections, missing_core, strip_running_lines
from tests.fakes_a2 import FakeCtx, fixture

IVABRADINE = {"id": "ing-iva", "inn_en": "ivabradine", "atc_code": "C01EB17", "terms": {}}
CARVEDILOL = {"id": "ing-car", "inn_en": "carvedilol", "atc_code": "C07AG02", "terms": {}}
PARACETAMOL = {"id": "ing-par", "inn_en": "paracetamol", "atc_code": "N02BE01", "terms": {}}
READERS = {"spc-cbg": cbg, "spc-famhp": famhp, "spc-aifa": aifa, "spc-mpa": mpa, "spc-infomed": infomed,
           "spc-hpra": hpra, "spc-basg": basg, "spc-lyfja": lyfja}


class PostCtx(FakeCtx):
    """``FakeCtx`` that also answers ``post``: ``posts`` maps a URL to a fixture path, bytes or an HTTP status."""

    def __init__(self, routes=None, posts=None):
        super().__init__(routes)
        self.posts = dict(posts or {})
        self.sent: list[tuple[str, object, dict | None]] = []

    def post(self, url, *, json=None, data=None, headers=None, accept=None, raise_for_status=True):
        self.requests.append(("POST", url, headers))
        self.sent.append((url, json if json is not None else data, headers))
        hit = self.posts.get(url)
        if hit is None:
            return Fetched(404, url, b"", "text/html")
        if isinstance(hit, int):
            return Fetched(hit, url, b"", "application/json")
        return Fetched(200, url, fixture(hit) if isinstance(hit, str) else hit, "application/json")


def test_the_eight_readers_are_watched_and_catalogued():
    _regulators, sources, _ = load_catalogue()
    by_id = {s.id: s for s in sources}
    for source_id, mod in READERS.items():
        assert MODULES[source_id] == mod.__name__.rsplit(".", 1)[1]
        assert mod.SOURCE_ID == source_id
        assert by_id[source_id].kind == "spc"


# ───────────────────────────── dates and running lines, every EU reader ─────────────────────────────

@pytest.mark.parametrize("text, want", [
    ("27. febrúar 2020.", date(2020, 2, 27)),            # Iceland
    ("2. desember 2024", date(2024, 12, 2)),
    ("14. ágúst 2023", date(2023, 8, 14)),
    ("12.2021\nREZEPTPFLICHT", date(2021, 12, 1)),        # Austria: month and year only
    ("12/2022", date(2022, 12, 1)),
    ("Juli 2026", date(2026, 7, 1)),
    ("25 de outubro de 2016", date(2016, 10, 25)),
    ("17.03.2025", date(2025, 3, 17)),
    ("2025-02-17", date(2025, 2, 17)),
    ("Datum van herziening van de tekst", None),
    (None, None),
])
def test_label_dates_as_written_never_completed_with_today(text, want):
    assert label_date(text) == want


def test_a_file_is_dated_by_the_latest_section_10_of_its_smpcs():
    assert label_revision({"4.3": "x", "10": "RESUMO", "smpc2:10": "11 de fevereiro de 2022"}) == date(2022, 2, 11)
    assert label_revision({"10": "03/2021", "smpc2:10": "12/2022"}) == date(2022, 12, 1)
    assert label_revision({"4.3": "x"}) is None


def _smpc(version: str, month: str, contra: str) -> str:
    body = [("1. NAAM VAN HET GENEESMIDDEL\nX 5 mg\n4. KLINISCHE GEGEVENS\n4.1 Therapeutische indicaties\n"
             "Angina pectoris bij volwassenen.\n"),
            "4.2 Dosering en wijze van toediening\nTweemaal daags.\n4.3 Contra-indicaties\n" + contra + "\n",
            "4.4 Bijzondere waarschuwingen\nLet op de hartfrequentie.\n4.5 Interacties\nCYP3A4.\n",
            "4.6 Zwangerschap\nNiet gebruiken.\n4.7 Rijvaardigheid\nFosfenen.\n4.8 Bijwerkingen\nFosfenen.\n",
            "4.9 Overdosering\nBradycardie.\n10. DATUM VAN HERZIENING VAN DE TEKST\n" + month + "\n"]
    return "\f".join(f"Sandoz B.V.        Page {n}/5\n{version}\nX 5 mg, tabletten\nRVG 1-2      {month}\n{page}"
                     for n, page in enumerate(body, start=1))


def test_running_headers_never_read_as_a_change():
    # CBG Carvedilol Sandoz, December 2025 against July 2026: its page headers made all of 4.2–4.9 look revised
    old = eu_label_sections(_smpc("1311-V14b", "Oktober 2025", "Shock."))
    new = eu_label_sections(_smpc("1311-V15", "Juli 2026", "Shock."))
    assert old["4.3"] == "Shock." and "Page" not in old["4.4"] and "1311" not in " ".join(old.values())
    assert [c["section"] for c in diff_sections(old, new)] == ["10"]


def test_a_real_change_still_shows_with_the_headers_gone():
    old = eu_label_sections(_smpc("1311-V14b", "Oktober 2025", "Shock."))
    new = eu_label_sections(_smpc("1311-V15", "Juli 2026", "Shock.\nCombinatie met cimetidine."))
    assert [c["section"] for c in diff_sections(old, new)] == ["4.3", "10"]


def test_a_short_file_is_left_as_it_is():
    text = "Page 1/2\nA\fPage 2/2\nB"
    assert strip_running_lines(text) == text


def test_a_line_repeated_inside_a_page_is_the_text_not_a_stamp():
    pages = ["Vaak\nHoofdpijn\nVaak\nDuizeligheid\nVaak\n" + "regel\n" * 20 + f"eind {n}" for n in range(6)]
    assert strip_running_lines("\f".join(pages)).count("Vaak") == 18


# ───────────────────────────── the Netherlands ─────────────────────────────

def _cbg_rows():
    return cbg.parse_metadata(fixture("spc-cbg/metadata_excerpt.csv").decode("utf-8-sig"))


def test_netherlands_national_products_only_with_their_previous_smpc():
    got = cbg.products_from(_cbg_rows(), ["ivabradine"])
    assert [p.national_id for p in got] == ["117810", "117827", "118269"]      # "RVG " with its trailing space
    p = got[1]
    assert p.product_name == "Prescoriel 6,25 mg/5 mg filmomhulde tabletten" and p.extra["smpc_date"] == "2024-04-30"
    assert p.extra["previous"].endswith("/archive/h117827_smpc_20221202_v0005.pdf")
    assert cbg.archive_date(p.extra["previous"]) == date(2022, 12, 2)
    assert "EU/1/05/316" not in {q.national_id for q in cbg.products_from(_cbg_rows(), ["ivabradine", "carvedilol"])}


def _cbg_routes() -> dict:
    return {cbg.METADATA: "spc-cbg/metadata_excerpt.csv",
            "https://www.geneesmiddeleninformatiebank.nl/smpc/h117827_smpc.pdf": "spc-cbg/h117827_smpc.pdf",
            "https://www.geneesmiddeleninformatiebank.nl/documents/smpc/archive/h117827_smpc_20221202_v0005.pdf":
                "spc-cbg/h117827_smpc_20221202_v0005.pdf"}


def test_netherlands_the_2024_revision_replays_as_a_change_in_the_watched_sections():
    got = replay.replay_cbg(FakeCtx(_cbg_routes()), "117827")
    assert got["dates"] == (date(2022, 12, 2), date(2024, 4, 30))
    assert {"4.2", "4.3", "4.8"} <= set(got["alerting"])
    added = " ".join(x["after"] for c in got["changes"] if c["section"] == "4.3" for x in c["changes"])
    assert "cimetidine" in added


def test_netherlands_the_archive_stamp_is_taken_out_of_the_old_smpc_only():
    ctx = FakeCtx(_cbg_routes())
    url = "https://www.geneesmiddeleninformatiebank.nl/documents/smpc/archive/h117827_smpc_20221202_v0005.pdf"
    stamped, _ = cbg.read_smpc(ctx, url, "old")
    clean, _ = cbg.read_smpc(ctx, url, "old", archived=True)
    assert "Oude versie" in " ".join(stamped.values()) and "Oude versie" not in " ".join(clean.values())


def test_netherlands_replay_of_a_product_without_a_previous_smpc_says_so():
    with pytest.raises(replay.ReplayError, match="no previous"):
        replay.replay_cbg(FakeCtx(_cbg_routes()), "29078")


# ───────────────────────────── Belgium ─────────────────────────────

def test_belgium_reads_the_national_rcp_of_human_products_only():
    rows = famhp.parse_documents(fixture("spc-famhp/documents_excerpt.csv").decode("utf-8-sig"))
    got = famhp.products_from(rows, ["ivabradine"])
    assert [(p.national_id, p.product_name) for p in got] == [("515377", "Ivabradine AB 7.5 mg film-coat. tabl.")]
    assert got[0].extra["published"] == "2022-07-01" and got[0].url.startswith(famhp.NATIONAL)


# ───────────────────────────── Italy ─────────────────────────────

def test_italy_searches_the_italian_inn_and_a_missing_page_leaves_the_list_partial():
    assert aifa.search_terms(IVABRADINE) == ["ivabradina"] and aifa.italian_inn("carvedilol") == "carvedilolo"
    got = aifa.discover(FakeCtx({aifa.SEARCH.format(term="ivabradina", page=0): "spc-aifa/ricerca_ivabradina_0.json"}),
                        IVABRADINE)
    assert [p.national_id for p in got] == ["044509", "044775", "044671", "044622", "045428"]
    assert not got.complete and got.gaps == ["term 1 page 2: HTTP 404"]


def test_italy_rcp_without_aifa_footer_and_stamp_dated_by_its_publication():
    s = aifa.snapshot(FakeCtx({"https://x.test/rcp": "spc-aifa/rcp_44509.pdf"}),
                      {"national_id": "044509", "extra": {"rcp": "https://x.test/rcp"}})
    text = " ".join(s.sections.values())
    assert missing_core(s.sections) == [] and s.doc_date == date(2020, 5, 30)
    assert aifa._STAMP not in text and "Documento reso disponibile" not in text


# ───────────────────────────── Sweden ─────────────────────────────

def test_sweden_approved_national_products_one_per_smpc():
    routes = {mpa.DETAIL.format(npl="20151029000022"): "spc-mpa/medprod_20151029000022.json",
              # every other product answers as Corlentor, a centrally authorised one: skipped
              mpa.DETAIL.format(npl="") + "*": "spc-mpa/medprod_20040607009420.json"}
    ctx = PostCtx(routes, {mpa.SEARCH: "spc-mpa/search_ivabradine.json"})
    got = mpa.discover(ctx, IVABRADINE)
    assert got.complete and [(p.national_id, p.product_name) for p in got] == [("20151029000022", "Ivabradin Krka")]
    p = got[0]
    assert p.extra["approved"] == "2023-09-25" and p.extra["smpc"].startswith("https://docetp.mpa.se/")
    assert mpa.listed_version({"extra": p.extra}) == "2023-09-25"
    assert all(body["status"] == "0" for _url, body, _h in ctx.sent)


def test_sweden_swedish_and_english_inn_spellings_alike():
    assert mpa.holds(["ivabradinhydroklorid"], "ivabradine") and mpa.holds(["karvedilol"], "carvedilol")
    assert not mpa.holds(["metoprolol"], "carvedilol")


# ───────────────────────────── Portugal ─────────────────────────────

def test_portugal_result_rows_and_count():
    page = fixture("spc-infomed/results_ivabradina_excerpt.html").decode("utf-8")
    rows = infomed.parse_rows(page)
    assert infomed.total_of(page) == 17 and len(rows) == 10
    assert rows[0] == {"id": "603243", "name": "Ivabradina Alter", "dci": "Ivabradina", "form": "Comprimido",
                       "strength": "5 mg", "holder": "Alter, S.A.", "generic": True}


def test_portugal_table_page_keeps_combinations():
    rows = infomed.parse_rows(fixture("spc-infomed/page_paracetamol_10.xml").decode("utf-8"))
    assert len(rows) == 10 and all(infomed.holds(r["dci"], "paracetamol") for r in rows)
    assert not infomed.holds("Ibuprofeno + Paracetamol", "ibuprofen")


def test_portugal_two_smpcs_in_one_file_and_the_infarmed_stamp_taken_out():
    s = infomed.snapshot(FakeCtx({"https://x.test/rcm": "spc-infomed/rcm_604022.pdf"}),
                         {"national_id": "604022", "extra": {"rcm": "https://x.test/rcm"}})
    assert missing_core(s.sections) == [] and {"smpc2:4.3", "smpc2:4.8"} <= set(s.sections)
    assert "APROVADO EM" not in " ".join(s.sections.values())
    assert s.doc_date == date(2022, 2, 11)                    # from the second SmPC's section 10


def test_portugal_stamp_lines():
    text = "4.3 Contra-indicações\nChoque.\n  APROVADO EM\n  29-06-2022\n  INFARMED\n4.4 Advertências\n"
    assert infomed._APPROVED.sub("", text) == "4.3 Contra-indicações\nChoque.\n\n4.4 Advertências\n"


# ───────────────────────────── Ireland ─────────────────────────────

FAKE_KEY = "made-up-key-for-tests=="
HPRA_API = f"https://sfapi.hpra.ie/api/HumanApprovedProducts?code={FAKE_KEY}"
HPRA_PAGE = f'<script>var productsListAPI = "{HPRA_API}";</script>'.encode()


def test_ireland_national_products_with_an_spc_through_the_pages_own_search():
    ctx = PostCtx({hpra.SEARCH_PAGE: HPRA_PAGE}, {HPRA_API: "spc-hpra/search_ivabradine.json"})
    got = hpra.discover(ctx, IVABRADINE)
    assert got.complete and [p.national_id for p in got] == ["20480", "26766", "20479", "26767"]
    assert all(p.extra["spc"].lower().endswith(".pdf") for p in got)          # the "Human SPC" document
    url, body, headers = ctx.sent[0]
    assert body["query"] == "ivabradine" and body["status"] == "Authorised" and headers["X-Client-App"]


def test_ireland_key_never_shown():
    assert FAKE_KEY not in redact(HPRA_API) and "code=<redacted>" in redact(f"failed: {HPRA_API}")
    canada = "https://health-products.canada.ca/api/drug/activeingredient/?lang=en&type=json&code=94728"
    assert redact(canada) == canada


def test_ireland_a_refused_key_fails_the_source_without_showing_it():
    ctx = PostCtx({hpra.SEARCH_PAGE: HPRA_PAGE}, {HPRA_API: 401})
    with pytest.raises(FetchError) as e:
        hpra.discover(ctx, IVABRADINE)
    assert FAKE_KEY not in str(e.value) and FAKE_KEY not in e.value.url


def test_ireland_a_page_without_the_search_address_is_a_parse_error():
    assert hpra.api_address(HPRA_PAGE.decode()) == HPRA_API
    with pytest.raises(ParseError):
        hpra.discover(PostCtx({hpra.SEARCH_PAGE: b"<html></html>"}), IVABRADINE)


# ───────────────────────────── Austria ─────────────────────────────

FAKE_TOKEN = "made-up-token-for-tests"
BASG_INDEX = b'<html><head><base href="/de/"></head><body><script src="main-TEST1234.js" type="module"></script>'
BASG_SCRIPT = f'x={{production:!0,apiUrl:"https://medikamente.basg.gv.at/api",apiToken:"{FAKE_TOKEN}"}}'.encode()
BASG_SEARCH = "https://medikamente.basg.gv.at/api/api/v1/medication/search?page=1&size=100"


def _basg_ctx(answer) -> PostCtx:
    return PostCtx({basg.SITE: BASG_INDEX, basg.SITE + "de/main-TEST1234.js": BASG_SCRIPT}, {BASG_SEARCH: answer})


def test_austria_national_products_with_a_fachinformation():
    ctx = _basg_ctx("spc-basg/search_ivabradin.json")
    got = basg.discover(ctx, IVABRADINE)
    assert got.complete and len(got) == 14 and not any(p.national_id.startswith("EU/") for p in got)
    p = next(p for p in got if p.national_id == "137618")
    assert p.product_name == "Ivabradin Stada 5 mg Filmtabletten" and basg.listed_version({"extra": p.extra}) == "2022-02-02"
    assert p.url == "https://medikamente.basg.gv.at/documents/137618__DOTC_FACH_INFO.pdf"
    _url, body, headers = ctx.sent[0]
    assert body["substance"] == "ivabradin" and headers["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_austria_a_refused_token_fails_the_source_without_showing_it():
    with pytest.raises(FetchError) as e:
        basg.discover(_basg_ctx(403), IVABRADINE)
    assert FAKE_TOKEN not in str(e.value)


def test_austria_a_script_without_the_token_is_a_parse_error():
    assert basg.front_end("", "no address here") is None
    ctx = PostCtx({basg.SITE: BASG_INDEX, basg.SITE + "de/main-TEST1234.js": b"x={}"})
    with pytest.raises(ParseError):
        basg.discover(ctx, IVABRADINE)


def test_austria_fachinformation_dated_by_stand_der_information():
    s = basg.snapshot(FakeCtx({"https://x.test/fi": "spc-basg/137618__DOTC_FACH_INFO.pdf"}),
                      {"national_id": "137618", "extra": {"fi": "https://x.test/fi", "valid": "2022-02-02"}})
    assert missing_core(s.sections) == [] and s.doc_date == date(2021, 12, 1)       # "12.2021"


# ───────────────────────────── Iceland ─────────────────────────────

def _items(rel: str) -> list[dict]:
    return json.loads(fixture(rel))


def test_iceland_one_product_per_smpc_and_only_our_ingredient():
    got = lyfja.products_from(_items("spc-lyfja/atc_C07AG.json"), CARVEDILOL)        # Trandate is labetalol
    assert len(got) == 1
    p = got[0]
    assert p.product_name == "Carvedilol STADA 25 mg, 12,5 mg, 6,25 mg, 3,125 mg" and p.mah == "STADA Arzneimittel AG"
    assert p.extra["licences"] == ["IS/1/18/015/04", "IS/1/18/015/03", "IS/1/18/015/02", "IS/1/18/015/01"]
    assert p.extra["smpc"] == ("https://www.serlyfjaskra.is/FileRepos/562fdb14-7d21-ea11-80fb-00155d15460a/"
                               "Carvedilol_STADA-SmPC.pdf")
    assert lyfja.listed_version({"extra": p.extra}) == "562fdb14-7d21-ea11-80fb-00155d15460a@2020-03-02T09:59:43"


def test_iceland_combinations_found_parallel_imports_and_central_products_skipped():
    got = lyfja.products_from(_items("spc-lyfja/atc_N02BE_excerpt.json"), PARACETAMOL)
    assert [p.product_name for p in got] == ["Paracetamol Medical Valley 1 g, 500 mg", "Panodil Extra 500/65 mg",
                                             "Panodil 1 g, 500 mg"]                    # not Paracet (Heilsa)
    assert lyfja.products_from(_items("spc-lyfja/atc_C01EB.json"), IVABRADINE) == []   # Procoralan: EU/1/05/316


def test_iceland_searches_the_atc_group_and_reports_an_ingredient_without_one():
    ctx = FakeCtx({lyfja.SEARCH.format(atc="C07AG"): "spc-lyfja/atc_C07AG.json"})
    got = lyfja.discover(ctx, CARVEDILOL)
    assert got.complete and len(got) == 1 and ctx.requests[0][1].endswith("query=C07AG*")
    none = lyfja.discover(FakeCtx(), {"id": "x", "inn_en": "guaifenesin", "terms": {}})
    assert not none.complete and list(none) == []
    failed = lyfja.discover(FakeCtx(), CARVEDILOL)
    assert failed.gaps == ["ATC C07AG: HTTP 404"]


def test_iceland_smpc_sections_and_icelandic_revision_date():
    s = lyfja.snapshot(FakeCtx({"https://x.test/is": "spc-lyfja/Carvedilol_STADA-SmPC.pdf"}),
                       {"national_id": "x", "product_name": "Carvedilol STADA", "extra": {"smpc": "https://x.test/is"}})
    assert missing_core(s.sections) == [] and s.doc_date == date(2020, 2, 27)       # "27. febrúar 2020."


# ───────────────────────────── the live read check ─────────────────────────────

def test_read_check_lists_and_reads_and_says_what_it_found():
    ctx = FakeCtx({lyfja.SEARCH.format(atc="C01EB"): "spc-lyfja/atc_C01EB.json",
                   lyfja.SEARCH.format(atc="C07AG"): "spc-lyfja/atc_C07AG.json",
                   lyfja.FILES.format(name="562fdb14-7d21-ea11-80fb-00155d15460a/Carvedilol_STADA-SmPC.pdf"):
                       "spc-lyfja/Carvedilol_STADA-SmPC.pdf"})
    lines, ok = read_check.check(ctx, "lyfja")
    assert ok and lines[0] == "### spc-lyfja (IS)" and "- ivabradine: 0 products" in lines
    assert any("10 sections, dated 2020-02-27" in x for x in lines)


def test_read_check_fails_a_database_that_lists_nothing():
    lines, ok = read_check.check(FakeCtx(), "lyfja")
    assert not ok and any("list not read to its end: ATC C01EB: HTTP 404" in x for x in lines)
