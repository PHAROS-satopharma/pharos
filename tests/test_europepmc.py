"""Europe PMC literature watch (collectors/parsers/europepmc.py): NCBI's words searched as phrases among journal
articles and preprints, paged by cursor, the papers new to PHAROS read 100 at a time, and a paper NCBI stored never
stored twice.

Europe PMC is served from the real answers saved in tests/fixtures/europepmc/ (carvedilol, first indexed 20 October
to 6 November 2026, read 25 ids a page on 6 November 2026: four pages, the last one empty); a lite query answers each
paper it names with its real saved record.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.matching import Term
from collectors.parsers import europepmc, pubmed
from collectors.parsers._literature import Elsewhere, doi_key, found_also
from collectors.parsers.base import ParseError
from collectors.run import Runner, select_sources

FIX = Path(__file__).resolve().parent / "fixtures" / "europepmc"
_, SOURCES, _ = load_catalogue()
SRC = next(s for s in SOURCES if s.id == "europepmc")
TODAY = date.today()
YEAR_AGO = pubmed.months_back(TODAY, 12)
QUERY = re.compile(r'^\(TITLE_ABS:"((?:[^"\\]|\\.)*)"(?: OR TITLE_ABS:"(?:[^"\\]|\\.)*")*\) '
                   r'AND \(SRC:MED OR SRC:PMC OR SRC:PPR\) AND '
                   r'FIRST_IDATE:\[(\d{4}-\d\d-\d\d) TO (\d{4}-\d\d-\d\d)\]$')
ASKED = re.compile(r"\(SRC:([A-Z]{3}) AND EXT_ID:([A-Za-z0-9]+)\)")


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


LITE = load("lite-carvedilol.json")["resultList"]["result"]
CARVEDILOL = {load(f"idlist-carvedilol-p{n}.json")["request"]["cursorMark"]: f"idlist-carvedilol-p{n}.json"
              for n in range(4)}
PREPRINT_DOI = "10.21203/rs.3.rs-10956313/v1"


class Epmc:
    """Europe PMC: an idlist search answers its words with their saved pages (by cursor), any other words with
    the real "no result" answer; a lite query answers each paper it names with its saved record."""

    def __init__(self, searches: dict | None = None) -> None:
        self.searches = searches if searches is not None else {"carvedilol": CARVEDILOL}
        self.calls: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p = dict(req.url.params)
        assert req.headers["user-agent"] == europepmc.USER_AGENT
        assert p["format"] == "json" and p["synonym"] == "false"
        assert "email" not in p and "@" not in str(req.url)        # the mailbox is in the header, never logged
        self.calls.append(p)
        if p["resultType"] == "idlist":
            m = QUERY.match(p["query"])
            assert m, p["query"]
            pages = self.searches.get(m[1], {})
            name = pages.get(p["cursorMark"], "idlist-empty.json")
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  content=(FIX / name).read_bytes())
        assert p["resultType"] == "lite", p
        asked = set(ASKED.findall(p["query"]))
        assert asked and len(asked) <= europepmc.RECORD_BATCH
        rows = [r for r in LITE if (r["source"], r["id"]) in asked]
        return httpx.Response(200, json={"version": "6.9", "hitCount": len(rows), "resultList": {"result": rows}})

    def idlists(self, words: str | None = None) -> list[dict]:
        return [c for c in self.calls if c["resultType"] == "idlist"
                and (words is None or QUERY.match(c["query"])[1] == words)]

    def windows(self, words: str) -> set[tuple[date, date]]:
        return {(date.fromisoformat(QUERY.match(c["query"])[2]), date.fromisoformat(QUERY.match(c["query"])[3]))
                for c in self.idlists(words)}

    def lites(self) -> list[dict]:
        return [c for c in self.calls if c["resultType"] == "lite"]


def context(tmp_path, server, run_id: str = "run") -> FetchContext:
    ctx = FetchContext(None, run_id, archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(server), host_gap_s=0)
    ctx._sleep = lambda s: None
    return ctx


def source(**options) -> object:
    return dataclasses.replace(SRC, options={**SRC.options, **options})


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "NCBI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


# ───────────────────────────── the catalogue and the searches ─────────────────────────────

def test_europe_pmc_runs_with_the_literature_runs():
    assert SRC.kind == "literature" and SRC.schedule == "daily" and SRC.parser == "europepmc"
    assert SRC.page_url == "https://europepmc.org/"
    assert SRC.options["look_back_months"] == 12 and SRC.options.get("backfill_all") is True
    assert int(SRC.options["max_new_items"]) >= 400 and SRC.options["search_budget_min"] > 0
    assert "europepmc" in [s.id for s in select_sources(SOURCES, "literature", None, False)]
    assert "europepmc" in [s.id for s in select_sources(SOURCES, "daily", None, False)]


def test_ncbis_words_once_each_as_a_quoted_phrase():
    got = europepmc.searches(["carvedilol", "lornoxicam"],
                             {"carvedilol": ["beta blockers", "Beta Blockers"], "lornoxicam": ["NSAID"]})
    assert [(s.query, s.kind, s.db) for s in got] == [
        ("carvedilol", "name", "europepmc"), ("lornoxicam", "name", "europepmc"),
        ("beta blockers", "class", "europepmc"), ("NSAID", "class", "europepmc")]
    assert got[2].key == ("europepmc", "beta blockers")
    assert (europepmc.query(got[2], date(2026, 10, 20), date(2026, 11, 6))
            == '(TITLE_ABS:"beta blockers") AND (SRC:MED OR SRC:PMC OR SRC:PPR) AND FIRST_IDATE:[2026-10-20 TO 2026-11-06]')
    # a name with its other English names: each in the title or abstract, as NCBI's [tiab]
    para = europepmc.searches(["paracetamol"], {}, {"paracetamol": ["acetaminophen"]})[0]
    assert (para.key, para.also) == (("europepmc", "paracetamol"), ("acetaminophen",))
    assert europepmc.query(para, date(2026, 11, 6), date(2026, 11, 6)).startswith(
        '(TITLE_ABS:"paracetamol" OR TITLE_ABS:"acetaminophen") AND ')
    # a quote or a backslash cannot end the phrase early (a broken query is silently half-read by Europe PMC)
    assert europepmc.phrase('5-HT3 "setrons" \\ x') == '"5-HT3 \\"setrons\\" \\\\ x"'


# ───────────────────────────── paging and parsing ─────────────────────────────

def test_every_page_is_read_until_the_cursor_ends(tmp_path):
    server = Epmc()
    ctx = context(tmp_path, server)
    s = europepmc.searches(["carvedilol"], {})[0]
    hits = europepmc.search_hits(ctx, s, date(2026, 10, 20), date(2026, 11, 6), page=25)
    ctx.close()
    # 56 counted, 53 listed: the count is never the stop, the empty last page without a next cursor is
    assert len(hits) == len({h.key for h in hits}) == 53
    assert [c["cursorMark"] for c in server.calls] == list(CARVEDILOL)
    assert all(c["pageSize"] == "25" for c in server.calls)
    by_key = {h.key: h for h in hits}
    assert by_key[("PPR", "PPR1350007")] == europepmc.Hit("PPR", "PPR1350007")
    assert by_key[("PMC", "PMC13690626")].pmcid == "PMC13690626"
    assert by_key[("MED", "42897877")].pmid == "42897877"


def test_a_cursor_that_does_not_move_ends_the_paging(tmp_path):
    page = load("idlist-carvedilol-p0.json")
    page["nextCursorMark"] = "*"
    calls = []

    def server(req):
        calls.append(req)
        return httpx.Response(200, json=page)

    ctx = context(tmp_path, server)
    hits = europepmc.search_hits(ctx, europepmc.searches(["carvedilol"], {})[0], TODAY, TODAY)
    ctx.close()
    assert len(calls) == 1 and len(hits) == len(page["resultList"]["result"])


def test_an_answer_without_its_result_list_is_a_parse_error(tmp_path):
    ctx = context(tmp_path, lambda req: httpx.Response(200, json={"version": "6.9", "hitCount": 3}))
    with pytest.raises(ParseError):
        europepmc.search_hits(ctx, europepmc.searches(["carvedilol"], {})[0], TODAY, TODAY)
    ctx.close()


def test_one_item_per_paper_with_ncbis_fields_and_the_preprint_flag(tmp_path):
    server = Epmc()
    ctx = context(tmp_path, server)
    items = europepmc.list_items(ctx, source(terms=["carvedilol"]))
    ctx.close()
    assert len(items) == 53
    assert len(server.lites()) == 1                         # 53 papers, one query of at most 100
    by = {it.external_id: it for it in items}

    pre = by["PPR1350007"]
    assert pre.url == "https://europepmc.org/article/PPR/PPR1350007" and pre.doc_type == "literature"
    assert pre.published == date(2026, 10, 26) and pre.lang == "en"
    s = pre.structured
    assert s["preprint"] is True and s["journal"] == "Research Square" and s["doi"] == PREPRINT_DOI
    assert s["pmid"] is None and s["pmcid"] is None and s["pubmed_url"] is None and s["pmc_url"] is None
    assert s["europepmc_id"] == "PPR1350007" and s["europepmc_url"] == pre.url
    assert s["found_in"] == ["europepmc"] and s["query_term"] == ["carvedilol"]
    assert s["queries"] == [{"query": "carvedilol", "kind": "name", "db": ["europepmc"]}]
    assert s["class_only"] is False and s["look_back"] is False and s["pubtype"] == ["preprint"]

    med = by["42968865"].structured                        # in PubMed and in PMC: both links, stored by PMID
    assert med["pmid"] == "42968865" and med["pmcid"] == "PMC13724075" and med["preprint"] is False
    assert med["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/42968865/"
    assert med["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13724075/"
    assert med["journal"] == "Cureus" and med["doi"] == "10.7759/cureus.117348"
    assert med["authors"][0] == "Gurijala R" and len(med["authors"]) == 6
    assert by["PMC13690626"].structured["pmcid"] == "PMC13690626"     # a PMC full text with no PubMed record
    assert by["PMC13690626"].structured["pmid"] is None

    assert by["42923775"].structured["case_report"] == {"reason": "pubtype"}     # "journal article; case reports"
    assert by["42910044"].structured["case_report"] == {"reason": "title"}       # typed "case-study", titled "A Case Report"
    assert sum(1 for it in items if it.structured["case_report"]) == 8
    assert not any(it.structured["preprint"] for k, it in by.items() if k != "PPR1350007")


def test_the_abstract_a_case_from_a_preprint_is_read_from(tmp_path):
    rec = {"id": "PPR1350007", "source": "PPR", "title": "Carvedilol <i>in vivo</i>",
           "abstractText": "<title>Abstract</title> <p>First   paragraph.</p><h4>Methods</h4><p>Second.</p>"}

    def server(req):
        assert req.url.params["query"] == "EXT_ID:PPR1350007 AND SRC:PPR" and req.url.params["resultType"] == "core"
        return httpx.Response(200, json={"hitCount": 1, "resultList": {"result": [rec]}})

    ctx = context(tmp_path, server)
    assert europepmc.abstract(ctx, "PPR1350007") == "Carvedilol in vivo\nAbstract\nFirst paragraph.\nMethods\nSecond."
    with pytest.raises(ParseError):
        europepmc.abstract(ctx, "PPR1 OR SRC:MED")
    ctx.close()


# ───────────────────────────── one paper, one document ─────────────────────────────

def test_found_also_adds_the_database_to_the_paper_and_its_words():
    s = {"pmid": "1", "found_in": ["pubmed"], "query_term": ["carvedilol"],
         "queries": [{"query": "carvedilol", "kind": "name", "db": ["pubmed"]}]}
    got = found_also(s, "europepmc", {"Carvedilol": "name", "beta blockers": "class"})
    assert got["found_in"] == ["europepmc", "pubmed"] and got["query_term"] == ["carvedilol"]
    assert got["queries"] == [{"query": "beta blockers", "kind": "class", "db": ["europepmc"]},
                              {"query": "carvedilol", "kind": "name", "db": ["europepmc", "pubmed"]}]
    assert s["found_in"] == ["pubmed"]                                     # the stored value is not changed
    assert found_also(got, "europepmc", {"carvedilol": "name"}) == got     # twice is once
    assert doi_key("https://doi.org/10.1/AbC") == doi_key("doi: 10.1/abc") == "10.1/abc"
    assert doi_key("not a doi") is None
    other = Elsewhere([{"id": "d1", "external_id": "PMC5", "pmid": None, "pmcid": None, "doi": "10.1/X"}])
    assert other.find(pmcid="PMC5") == other.find(doi="10.1/x") == "d1" and other.find(pmid="5") is None


CARV_ID = "00000000-0000-4000-8000-0000000000c1"


def add_carvedilol(store: MemoryStore) -> None:
    store.ingredient[CARV_ID] = {"inn_en": "carvedilol", "atc_code": "C07AG02", "active": True}
    store.terms.append(Term(id="t-carv", term="carvedilol", lang="en", ingredient_id=CARV_ID, kind="inn"))


def ncbi_paper(store: MemoryStore, external_id: str, **structured) -> str:
    did = store.insert_document({
        "source_id": "pubmed", "external_id": external_id, "url": f"https://pubmed.ncbi.nlm.nih.gov/{external_id}/",
        "title_orig": f"Paper {external_id}", "lang": "en", "doc_type": "literature",
        "published_date": date(2026, 10, 25), "is_backfill": False,
        "structured": {"found_in": ["pubmed"], "query_term": ["carvedilol"],
                       "queries": [{"query": "carvedilol", "kind": "name", "db": ["pubmed"]}], **structured}})
    assert did
    return did


def live_like_store() -> tuple[MemoryStore, dict[str, str]]:
    """Carvedilol watched, NCBI read for months: three of Europe PMC's papers are already stored from NCBI, one
    under its PMID, one under its PMC id and one (the preprint) known only by its DOI."""
    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    add_carvedilol(store)
    ncbi = {"pmid": ncbi_paper(store, "42897877", pmid="42897877"),
            "pmcid": ncbi_paper(store, "PMC13690626", pmid=None, pmcid="PMC13690626", found_in=["pmc"],
                                queries=[{"query": "carvedilol", "kind": "name", "db": ["pmc"]}]),
            "doi": ncbi_paper(store, "40000001", pmid="40000001", doi=PREPRINT_DOI.upper())}
    store.source["pubmed"]["last_ok_at"] = datetime.now(timezone.utc) - timedelta(days=1)
    return store, ncbi


class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called")

    send_document = send_message


def run_europepmc(store: MemoryStore, tmp_path, server: Epmc, **options):
    run_id = store.create_run("cron", "test-sha", "literature")
    ctx = context(tmp_path, server, run_id)
    settings = {**store.settings(), "alert_max_age_days": 100_000}
    runner = Runner(store, ctx, Notifier(store, settings, telegram=ExplodingTelegram()), settings)
    stats = runner.run_source(source(page_size=25, **options))
    ctx.close()
    return stats


def docs(store: MemoryStore, source_id: str = "europepmc") -> dict[str, dict]:
    return {d["external_id"]: d for d in store.document.values() if d["source_id"] == source_id}


def test_a_paper_ncbi_stored_is_only_marked_found_and_the_rest_looks_back_12_months(tmp_path):
    store, ncbi = live_like_store()
    server = Epmc()
    stats = run_europepmc(store, tmp_path, server)
    assert not stats.failed, stats.error
    assert server.windows("carvedilol") == {(YEAR_AGO, TODAY)}             # a new search: 12 months, once
    assert server.windows("lornoxicam") == {(YEAR_AGO, TODAY)}
    asked = {k for c in server.lites() for k in ASKED.findall(c["query"])}
    assert ("MED", "42897877") not in asked and ("PMC", "PMC13690626") not in asked     # known by id: not read
    assert ("PPR", "PPR1350007") in asked                                   # its DOI is only in its record

    got = docs(store)
    assert len(got) == 53 - 3 and stats.new == 50
    assert not {"42897877", "PMC13690626", "PPR1350007"} & set(got)
    assert all(d["is_backfill"] and d["structured"]["look_back"] for d in got.values())    # history: no alert
    assert stats.alerts == [] and not [n for n in store.notification if n["kind"] == "immediate"]
    for key, did in ncbi.items():
        s = store.document[did]["structured"]
        assert "europepmc" in s["found_in"], key
        assert "europepmc" in next(q["db"] for q in s["queries"] if q["query"] == "carvedilol"), key
        assert s["query_term"] == ["carvedilol"]
    assert store.document[ncbi["pmcid"]]["structured"]["found_in"] == ["europepmc", "pmc"]
    rows = store.literature_searches()
    assert rows[("europepmc", "carvedilol")]["look_back_done_at"] and rows[("europepmc", "carvedilol")]["kind"] == "name"
    assert rows[("europepmc", "lornoxicam")]["look_back_done_at"]
    assert ("pubmed", "carvedilol") not in rows                              # NCBI's own searches are its own
    # every paper is linked to the ingredient by its search word, and each is a notice of its own
    linked = {m["document_id"] for m in store.match if m["ingredient_id"] == CARV_ID}
    assert {d["id"] for d in got.values()} <= linked

    # the next day: every search reads from the last complete run, nothing is read or stored twice
    server = Epmc()
    stats = run_europepmc(store, tmp_path, server)
    since = store.source["europepmc"]["last_ok_at"].date() - timedelta(days=3)
    assert not stats.failed and stats.new == 0
    assert server.windows("carvedilol") == {(since, TODAY)}
    # only the preprint's record is read again: NCBI's paper is known by its DOI, which the id list does not carry
    assert [ASKED.findall(c["query"]) for c in server.lites()] == [[("PPR", "PPR1350007")]]
    assert len(docs(store)) == 50 and len(docs(store, "pubmed")) == 3


def test_new_papers_over_the_cap_wait_and_a_look_back_cut_short_continues(tmp_path):
    store, _ = live_like_store()
    stats = run_europepmc(store, tmp_path, Epmc(), max_new_items=20)
    # 20 records read: the preprint first, whose DOI NCBI's paper has (not stored), then 19 papers
    assert not stats.failed and stats.new == 19
    assert store.literature_searches()[("europepmc", "carvedilol")]["look_back_done_at"] is None

    server = Epmc()
    stats = run_europepmc(store, tmp_path, server)
    assert not stats.failed and stats.new == 31
    assert server.windows("carvedilol") == {(YEAR_AGO, TODAY)}             # its look-back again
    assert store.literature_searches()[("europepmc", "carvedilol")]["look_back_done_at"]
    assert len(docs(store)) == 50


def test_new_papers_over_the_cap_keep_the_window(tmp_path):
    store, _ = live_like_store()
    store.save_literature_searches([{"db": "europepmc", "query": q, "kind": "name", "look_back_from": YEAR_AGO,
                                     "history_until": TODAY - timedelta(days=5), "done": True}
                                    for q in ("carvedilol", "lornoxicam")])
    store.source["europepmc"]["last_ok_at"] = before = datetime.now(timezone.utc) - timedelta(days=2)
    stats = run_europepmc(store, tmp_path, Epmc(), max_new_items=20)
    assert not stats.failed and stats.new == 19                             # 20 read, the preprint NCBI's by DOI
    assert stats.error == "item cap reached: 31 new item(s) wait for the next run"
    assert store.source["europepmc"]["last_ok_at"] == before                # not complete: the days are read again
    assert not any(d["structured"]["look_back"] for d in docs(store).values())     # a daily window's papers


def test_searching_stops_at_its_time_budget_and_the_rest_waits(tmp_path, monkeypatch):
    store, _ = live_like_store()
    ticks = iter([0.0, 0.0, 10_000.0, 10_000.0])
    monkeypatch.setattr(europepmc, "_clock", lambda: next(ticks))
    server = Epmc()
    ctx = context(tmp_path, server)
    ctx.store = store
    src = source(page_size=25, search_budget_min=1, terms=["carvedilol", "lornoxicam"])
    items = europepmc.list_items(ctx, src)
    europepmc.after_store(ctx, src, items, {it.external_id for it in items})
    ctx.close()
    assert server.idlists("carvedilol") and not server.idlists("lornoxicam")
    rows = store.literature_searches()
    assert rows[("europepmc", "carvedilol")]["look_back_done_at"]
    assert ("europepmc", "lornoxicam") not in rows                          # not searched: looked back next time


def test_the_searches_done_before_go_first(tmp_path):
    store, _ = live_like_store()
    store.save_literature_searches([{"db": "europepmc", "query": "carvedilol", "kind": "name",
                                     "look_back_from": YEAR_AGO, "history_until": TODAY, "done": True}])
    server = Epmc()
    ctx = context(tmp_path, server)
    ctx.store = store
    europepmc.list_items(ctx, source(page_size=25, terms=["lornoxicam", "carvedilol"]))
    ctx.close()
    words = [QUERY.match(c["query"])[1] for c in server.idlists()]
    assert words[0] == "carvedilol" and words[-1] == "lornoxicam"           # its daily window before a look-back


def test_ncbi_never_stores_again_a_paper_europe_pmc_stored_first(tmp_path):
    store, _ = live_like_store()
    assert not run_europepmc(store, tmp_path, Epmc()).failed
    did = docs(store)["42968865"]["id"]
    other = Elsewhere.load(store, "pubmed")
    assert other.find(pmid="42968865") == other.find(pmcid="PMC13724075") == did
    assert other.find(doi="10.7759/CUREUS.117348") == did
    assert Elsewhere.load(store, "europepmc").find(pmid="42968865") is None     # its own papers are not "elsewhere"
