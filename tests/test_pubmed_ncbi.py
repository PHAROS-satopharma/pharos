"""NCBI literature (collectors/parsers/pubmed.py): PubMed and PubMed Central searched as a person types them,
paged until every id is in, one item per paper, and a 12-month look-back the first time a word is searched.

E-utilities is served from the real answers saved in tests/fixtures/pubmed/ (levofloxacin and fluoroquinolones,
entered 3-4 November 2026); esummary answers each id asked for with its real saved record.
"""

from __future__ import annotations

import dataclasses
import json
import logging
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
from collectors.parsers import pubmed
from collectors.parsers.base import ParseError
from collectors.run import Runner

FIX = Path(__file__).resolve().parent / "fixtures" / "pubmed"
_, SOURCES, _ = load_catalogue()
SRC = next(s for s in SOURCES if s.id == "pubmed")
TODAY = date.today()
YEAR_AGO = pubmed.months_back(TODAY, 12) if hasattr(pubmed, "months_back") else None


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


RECORDS: dict[str, dict] = {"pubmed": {}, "pmc": {}}
for _db, _names in {"pubmed": ["esummary-pubmed-levofloxacin.json", "esummary-pubmed-fluoroquinolones.json",
                               "esummary.json"],
                    "pmc": ["esummary-pmc-levofloxacin.json"]}.items():
    for _n in _names:
        _res = load(_n)["result"]
        RECORDS[_db].update({u: _res[u] for u in _res["uids"]})

LEVO_PUBMED = {0: "esearch-pubmed-levofloxacin-p0.json", 2: "esearch-pubmed-levofloxacin-p2.json",
               4: "esearch-pubmed-levofloxacin-p4.json"}
LEVO = {("pubmed", "levofloxacin"): LEVO_PUBMED, ("pmc", "levofloxacin"): "esearch-pmc-levofloxacin.json",
        ("pubmed", "fluoroquinolones"): "esearch-pubmed-fluoroquinolones.json"}


class Ncbi:
    """E-utilities: esearch answers (db, term) with its saved answer (by retstart when paged), any other
    search with the real "no result" answer; esummary answers each id with its saved record."""

    def __init__(self, searches: dict | None = None) -> None:
        self.searches = searches or {}
        self.calls: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p = dict(req.url.params)
        what = req.url.path.rsplit("/", 1)[-1].split(".")[0]
        self.calls.append({"what": what, "url": str(req.url), **p})
        if what == "esearch":
            f = self.searches.get((p["db"], p["term"]), "esearch-empty.json")
            if isinstance(f, dict):
                f = f.get(int(p["retstart"]), "esearch-empty.json")
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  content=(FIX / f).read_bytes())
        assert what == "esummary", req.url
        ids = p["id"].split(",")
        recs = RECORDS[p["db"]]
        result = {"uids": [u for u in ids if u in recs], **{u: recs[u] for u in ids if u in recs}}
        return httpx.Response(200, json={"header": {"type": "esummary", "version": "0.3"}, "result": result})

    def esearches(self, db: str | None = None, term: str | None = None) -> list[dict]:
        return [c for c in self.calls if c["what"] == "esearch"
                and (db is None or c["db"] == db) and (term is None or c["term"] == term)]

    def esummaries(self) -> list[dict]:
        return [c for c in self.calls if c["what"] == "esummary"]


def day(s: str) -> date:
    return datetime.strptime(s, "%Y/%m/%d").date()


def context(tmp_path, ncbi: Ncbi, run_id: str = "run") -> FetchContext:
    ctx = FetchContext(None, run_id, archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(ncbi), host_gap_s=0)
    ctx._sleep = lambda s: None
    return ctx


def source(**options) -> object:
    return dataclasses.replace(SRC, options={**SRC.options, **options})


# ───────────────────────────── searches ─────────────────────────────

def test_the_catalogue_runs_ncbi_daily_with_a_high_cap():
    assert SRC.schedule == "daily"
    assert int(SRC.options["max_new_items"]) >= 1000
    assert SRC.options["look_back_months"] == 12 and SRC.options.get("backfill_all") is True


def test_names_first_then_class_words_each_once_on_both_databases():
    got = pubmed.searches(["levofloxacin", "lornoxicam"],
                          {"levofloxacin": ["fluoroquinolones", "Fluoroquinolones"],
                           "lornoxicam": ["NSAID", "non-steroidal anti-inflammatory"]})
    assert [(s.query, s.kind, s.db) for s in got] == [
        ("levofloxacin", "name", "pubmed"), ("levofloxacin", "name", "pmc"),
        ("lornoxicam", "name", "pubmed"), ("lornoxicam", "name", "pmc"),
        ("fluoroquinolones", "class", "pubmed"), ("fluoroquinolones", "class", "pmc"),
        ("NSAID", "class", "pubmed"), ("NSAID", "class", "pmc"),
        ("non-steroidal anti-inflammatory", "class", "pubmed"),
        ("non-steroidal anti-inflammatory", "class", "pmc")]


def test_months_back():
    assert pubmed.months_back(date(2026, 11, 6), 12) == date(2025, 11, 6)
    assert pubmed.months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert pubmed.months_back(date(2024, 3, 31), 1) == date(2024, 2, 29)
    assert pubmed.months_back(date(2026, 1, 15), 2) == date(2025, 11, 15)


def test_the_search_is_the_words_as_typed_on_both_databases(tmp_path):
    ncbi = Ncbi()
    ctx = context(tmp_path, ncbi)
    pubmed.list_items(ctx, source(terms=["non-steroidal anti-inflammatory"]))
    calls = ncbi.esearches()
    assert [c["db"] for c in calls] == ["pubmed", "pmc"]
    for c in calls:
        assert "term=non-steroidal%20anti-inflammatory&" in c["url"] + "&"
        assert "%22" not in c["url"] and "%5B" not in c["url"]           # no quotes, no [field] tag
        assert c["term"] == "non-steroidal anti-inflammatory" and c["datetype"] == "edat"
        assert c["tool"] == "pharos" and c["retstart"] == "0"
    ctx.close()


def test_every_page_is_read(tmp_path):
    ncbi = Ncbi(LEVO)
    ctx = context(tmp_path, ncbi)
    ids = pubmed.esearch_ids(ctx, pubmed.Search("levofloxacin", "name", "pubmed"),
                             date(2026, 11, 3), date(2026, 11, 4), page=2)
    assert ids == ["42980339", "42980315", "42979212", "42976507", "42973869"]
    assert [(c["retstart"], c["retmax"]) for c in ncbi.esearches()] == [("0", "2"), ("2", "2"), ("4", "2")]
    assert {(c["mindate"], c["maxdate"]) for c in ncbi.esearches()} == {("2026/11/03", "2026/11/04")}
    ctx.close()


def test_a_window_over_the_esearch_limit_is_split(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(pubmed, "MAX_IDS", 4)          # 5 papers in two days, 2 + 3 per day
    by_day = {"2026/11/03": "esearch-pubmed-levofloxacin-1103.json",
              "2026/11/04": "esearch-pubmed-levofloxacin-1104.json"}

    def handler(req: httpx.Request) -> httpx.Response:
        p = dict(req.url.params)
        f = "esearch-pubmed-levofloxacin-p0.json" if p["mindate"] != p["maxdate"] else by_day[p["mindate"]]
        return httpx.Response(200, headers={"content-type": "application/json"}, content=(FIX / f).read_bytes())

    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    s = pubmed.Search("levofloxacin", "name", "pubmed")
    assert sorted(pubmed.esearch_ids(ctx, s, date(2026, 11, 3), date(2026, 11, 4))) == sorted(
        ["42980339", "42980315", "42979212", "42976507", "42973869"])
    monkeypatch.setattr(pubmed, "MAX_IDS", 2)          # one day over the limit: read, and said
    with caplog.at_level(logging.WARNING, logger="collectors.parsers.pubmed"):
        assert pubmed.esearch_ids(ctx, s, date(2026, 11, 4), date(2026, 11, 4))
    assert "only the first 2 are read" in caplog.text
    ctx.close()


def test_a_changed_answer_is_a_parse_error(tmp_path):
    with pytest.raises(ParseError):
        pubmed.summaries({"error": "x"}, ["1"])

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"esearchresult": {"count": "3"}})        # no id list

    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    with pytest.raises(ParseError):
        pubmed.esearch_ids(ctx, pubmed.Search("x", "name", "pubmed"), TODAY, TODAY)
    ctx.close()


def test_ncbi_is_read_at_its_own_pace(tmp_path, monkeypatch):
    monkeypatch.delenv("NCBI_API_KEY", raising=False)
    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(Ncbi()))
    pubmed.list_items(ctx, source(terms=["levofloxacin"]))
    assert ctx._host_gap[pubmed.EUTILS_HOST] == pytest.approx(0.34)   # 3 a second, not one per 2 s
    ctx.close()
    monkeypatch.setenv("NCBI_API_KEY", "k")
    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(Ncbi()))
    pubmed.list_items(ctx, source(terms=["levofloxacin"]))
    assert ctx._host_gap[pubmed.EUTILS_HOST] == pytest.approx(0.11)
    ctx.close()


# ───────────────────────────── papers ─────────────────────────────

def test_a_paper_in_both_databases_is_one_item_with_both_links(tmp_path):
    ncbi = Ncbi(LEVO)
    ctx = context(tmp_path, ncbi)
    items = pubmed.list_items(ctx, source(terms=["levofloxacin"], page_size=2))
    by_id = {i.external_id: i for i in items}
    assert len(items) == len(by_id) == 5 + 59 - 2                 # two papers are in both
    both = by_id["42979212"].structured
    assert by_id["42979212"].url == "https://pubmed.ncbi.nlm.nih.gov/42979212/"
    assert both["pmcid"] == "PMC13730105" and both["found_in"] == ["pmc", "pubmed"]
    assert both["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/42979212/"
    assert both["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13730105/"
    assert both["pubtype"] == ["Journal Article"] and both["doi"] == "10.2147/RRU.S650380"
    # found only in the full texts: the PMC link, and the PubMed one beside it
    pmc_only = by_id["42979440"]
    assert pmc_only.url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13729541/"
    assert pmc_only.structured["found_in"] == ["pmc"]
    assert pmc_only.structured["pubmed_url"] == "https://pubmed.ncbi.nlm.nih.gov/42979440/"
    # not in PubMed yet: stored under its PMC id
    no_pmid = by_id["PMC13727276"]
    assert no_pmid.url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13727276/"
    assert no_pmid.structured["pmid"] is None and no_pmid.published == date(2026, 10, 30)
    assert all(i.structured["query_term"] == ["levofloxacin"] for i in items)
    assert all(i.structured["queries"][0]["kind"] == "name" for i in items)
    assert not any(i.structured["class_only"] or i.structured["look_back"] for i in items)
    assert all(i.doc_type == "literature" for i in items)
    assert pubmed.aliases(by_id["42979212"]) == ["PMC13730105"] and pubmed.aliases(no_pmid) == []
    # every PMC record in one batch, no PubMed record asked for twice
    assert [c["db"] for c in ncbi.esummaries()] == ["pubmed", "pmc"]
    ctx.close()


# ───────────────────────────── the runner: look-back, then daily ─────────────────────────────

class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called")

    send_document = send_message


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET", "NCBI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


LEVO_ID, FQ_ID = "00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000a2"


def add_levofloxacin(store: MemoryStore) -> None:
    """Levofloxacin and its class, added in the app."""
    store.ingredient[LEVO_ID] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    store.ingredient_class.append((LEVO_ID, FQ_ID))
    store.terms += [Term(id="t-levo", term="levofloxacin", lang="en", ingredient_id=LEVO_ID, kind="inn"),
                    Term(id="ct-fq", term="fluoroquinolones", lang="en", class_id=FQ_ID, kind="class"),
                    Term(id="ct-fq-de", term="Fluorchinolone", lang="de", class_id=FQ_ID, kind="class")]


def live_like_store() -> MemoryStore:
    """As production before this change: lornoxicam and the NSAID class, PubMed read weekly for months."""
    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    store.insert_document({"source_id": "pubmed", "external_id": "42846100", "url": "https://pubmed.ncbi.nlm.nih.gov/42846100/",
                           "title_orig": "An old lornoxicam paper", "lang": "en", "doc_type": "literature",
                           "published_date": date(2026, 10, 7), "structured": {"pmid": "42846100"},
                           "is_backfill": False})
    store.source["pubmed"]["last_ok_at"] = datetime.now(timezone.utc) - timedelta(days=1)
    return store


def run_pubmed(store: MemoryStore, tmp_path, ncbi: Ncbi, **options):
    run_id = store.create_run("cron", "test-sha", "daily")
    ctx = context(tmp_path, ncbi, run_id)
    settings = {**store.settings(), "alert_max_age_days": 100_000}   # every fixture paper counts as new
    runner = Runner(store, ctx, Notifier(store, settings, telegram=ExplodingTelegram()), settings)
    stats = runner.run_source(source(page_size=2, **options))
    ctx.close()
    return stats


def windows(ncbi: Ncbi, db: str, term: str) -> set[tuple[date, date]]:
    return {(day(c["mindate"]), day(c["maxdate"])) for c in ncbi.esearches(db, term)}


def docs(store: MemoryStore) -> dict[str, dict]:
    return {d["external_id"]: d for d in store.document.values() if d["source_id"] == "pubmed"}


def test_a_new_ingredient_looks_back_12_months_once_then_reads_daily(tmp_path):
    store = live_like_store()
    store.save_literature_searches([      # lornoxicam's name was searched before; NSAID's words never were
        {"db": db, "query": "lornoxicam", "kind": "name", "look_back_from": date(2025, 11, 1),
         "history_until": date(2026, 11, 1), "done": True} for db in ("pubmed", "pmc")])
    add_levofloxacin(store)
    since = store.source["pubmed"]["last_ok_at"].date() - timedelta(days=3)

    ncbi = Ncbi(LEVO)
    stats = run_pubmed(store, tmp_path, ncbi)
    assert not stats.failed, stats.error
    for db in ("pubmed", "pmc"):
        assert windows(ncbi, db, "lornoxicam") == {(since, TODAY)}                 # already searched
        for term in ("levofloxacin", "fluoroquinolones", "NSAID", "nonsteroidal anti-inflammatory"):
            assert windows(ncbi, db, term) == {(YEAR_AGO, TODAY)}, (db, term)     # never searched
    assert not ncbi.esearches(term="Fluorchinolone")                               # English words only
    got = docs(store)
    assert len(got) == 1 + 62 + 7
    new = [d for k, d in got.items() if k != "42846100"]
    assert all(d["is_backfill"] and d["structured"]["look_back"] for d in new)     # history: no alert
    assert stats.alerts == [] and not [n for n in store.notification if n["kind"] == "immediate"]
    fq = [d for d in new if d["structured"]["query_term"] == ["fluoroquinolones"]]
    assert len(fq) == 7 and all(d["structured"]["class_only"] for d in fq)
    fq_issues = [i for i in store.issue.values() if i["anchor_document_id"] in {d["id"] for d in fq}]
    assert len(fq_issues) == 7 and all(i["class_only"] for i in fq_issues)        # the class digest's
    assert got["42979212"]["structured"]["pmc_url"] == "https://pmc.ncbi.nlm.nih.gov/articles/PMC13730105/"
    rows = store.literature_searches()
    assert all(r["look_back_done_at"] for r in rows.values())
    assert rows[("pmc", "levofloxacin")]["look_back_from"] == YEAR_AGO

    # the next day: every search reads from the last complete run, and nothing is read twice
    ncbi = Ncbi(LEVO)
    stats = run_pubmed(store, tmp_path, ncbi)
    since = store.source["pubmed"]["last_ok_at"].date() - timedelta(days=3)
    assert not stats.failed and stats.new == 0
    assert {(day(c["mindate"]), day(c["maxdate"])) for c in ncbi.esearches()} == {(since, TODAY)}
    assert ncbi.esummaries() == []


def test_a_look_back_cut_short_continues_on_the_next_run(tmp_path):
    store = live_like_store()
    add_levofloxacin(store)
    ncbi = Ncbi(LEVO)
    stats = run_pubmed(store, tmp_path, ncbi, max_new_items=40)
    assert not stats.failed and stats.new == 40
    rows = store.literature_searches()
    assert rows[("pubmed", "levofloxacin")]["look_back_done_at"]            # its 5 papers are in
    assert rows[("pmc", "levofloxacin")]["look_back_done_at"] is None       # 35 of its 59 are
    assert rows[("pubmed", "fluoroquinolones")]["look_back_done_at"] is None  # class papers wait
    assert {d["external_id"] for d in docs(store).values()} >= {"42980339", "42980315", "42979212"}

    ncbi = Ncbi(LEVO)
    stats = run_pubmed(store, tmp_path, ncbi, max_new_items=40)
    since = store.source["pubmed"]["last_ok_at"].date() - timedelta(days=3)
    assert not stats.failed
    assert windows(ncbi, "pubmed", "levofloxacin") == {(since, TODAY)}
    assert windows(ncbi, "pmc", "levofloxacin") == {(YEAR_AGO, TODAY)}             # its look-back again
    assert windows(ncbi, "pubmed", "fluoroquinolones") == {(YEAR_AGO, TODAY)}
    assert len(docs(store)) == 1 + 62 + 7
    assert all(d["is_backfill"] for k, d in docs(store).items() if k != "42846100")
    assert all(r["look_back_done_at"] for r in store.literature_searches().values())
    assert stats.alerts == []


def test_plan_windows():
    ctx = FetchContext(None, "run", archive=Archive(enabled=False))
    ctx.last_ok_at = datetime.now(timezone.utc) - timedelta(days=1)
    name = pubmed.Search("levofloxacin", "name", "pmc")
    cls = pubmed.Search("fluoroquinolones", "class", "pmc")
    opts = {"lookback_days": 10, "look_back_months": 12, "class_look_back_months": 6}
    normal = pubmed.Window(ctx.last_ok_at.date() - timedelta(days=3), TODAY, False)
    # never searched: the look-back, history
    assert pubmed.plan(ctx, name, None, opts, TODAY, True)[0] == [pubmed.Window(YEAR_AGO, TODAY, True)]
    assert pubmed.plan(ctx, cls, None, opts, TODAY, True)[0] == [
        pubmed.Window(pubmed.months_back(TODAY, 6), TODAY, True)]
    # done: the daily window
    done = {"look_back_from": YEAR_AGO, "history_until": TODAY - timedelta(days=5),
            "look_back_done_at": datetime.now(timezone.utc), "last_searched_at": datetime.now(timezone.utc)}
    assert pubmed.plan(ctx, name, done, opts, TODAY, True)[0] == [normal]
    # cut short five days ago: its days again as history, then what came since as new
    pending = {**done, "look_back_done_at": None}
    assert pubmed.plan(ctx, name, pending, opts, TODAY, True)[0] == [
        pubmed.Window(YEAR_AGO, TODAY - timedelta(days=5), True),
        pubmed.Window(TODAY - timedelta(days=4), TODAY, False)]
    # not searched for months (the ingredient was switched off): a new look-back
    stale = {**done, "last_searched_at": datetime.now(timezone.utc) - timedelta(days=120)}
    assert pubmed.plan(ctx, name, stale, opts, TODAY, True)[0] == [pubmed.Window(YEAR_AGO, TODAY, True)]
    # nothing to remember searches in (a quick local run): what is new only
    assert pubmed.plan(ctx, name, None, opts, TODAY, False)[0] == [normal]
    ctx.close()


def test_a_paper_stored_under_its_pmc_id_is_not_stored_again(tmp_path):
    store = live_like_store()
    add_levofloxacin(store)
    store.insert_document({"source_id": "pubmed", "external_id": "PMC13730105",
                           "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13730105/",
                           "title_orig": "Clinical Significance of Urine Culture", "lang": "en",
                           "doc_type": "literature", "published_date": date(2026, 10, 30),
                           "structured": {"pmid": None, "pmcid": "PMC13730105"}, "is_backfill": True})
    stats = run_pubmed(store, tmp_path, Ncbi(LEVO))
    assert not stats.failed
    assert "42979212" not in docs(store) and "PMC13730105" in docs(store)
    assert all(r["look_back_done_at"] for r in store.literature_searches().values())
