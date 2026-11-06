"""The search profile end to end on an in-memory store: levofloxacin, its group (Fluoroquinolones, searched)
and its parent class (Quinolone antibacterials, off until switched on). Notices go through the real Runner
(collectors/run.py) with a stub parser module; nothing leaves the machine and Telegram must never be called.

The acceptance tests of the Ingredients module review (6 November 2026):
  4. a notice that names only the group is found through the ingredient's class, as a class-only finding;
  5. a notice that names the ingredient is a direct finding;
  6. the parent class finds nothing while off, and its words (in their own languages) once switched on.
"""

from __future__ import annotations

import types
from datetime import date

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.models import Item
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.matching import Term
from collectors.run import Runner, SourceStats

_, SOURCES, _ = load_catalogue()
SRC = next(s for s in SOURCES if s.id == "ema-psusa")
# A parser with no detail page, no structured fields and no PDF columns: the title is what is matched.
MODULE = types.SimpleNamespace()


class ExplodingTelegram:
    def send_message(self, *a, **k):
        raise AssertionError("Telegram must not be called")

    send_document = send_message


def no_web(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"nothing may be fetched: {request.url}")


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


def profile(tmp_path):
    """levofloxacin with its own name, its group (on) and its parent class (off), as the daily run leaves them."""
    store = MemoryStore()
    sync_catalogue(store)
    store.ingredient["levo"] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    store.terms.append(Term(id="t-levo", term="levofloxacin", lang="en", mode="stem", ingredient_id="levo", kind="inn"))
    group = store.create_drug_class(code="J01MA", name_en="Fluoroquinolones", wikidata_qid="Q28801726", terms=[
        {"lang": "en", "term": "fluoroquinolone", "mode": "stem", "source": "wikidata"},
        {"lang": "de", "term": "Fluorchinolon", "mode": "stem", "source": "wikidata"}])
    parent = store.create_drug_class(code="J01M", name_en="Quinolone antibacterials", wikidata_qid="Q13669486", terms=[
        {"lang": "en", "term": "quinolone antibiotic", "mode": "stem", "source": "wikidata"},
        {"lang": "ja", "term": "ニューキノロン", "mode": "substring", "source": "wikidata"}])
    store.link_ingredient_class("levo", group)
    store.link_ingredient_class("levo", parent, relation="parent", enabled=False)
    run_id = store.create_run("manual", "test-sha")
    ctx = FetchContext(None, run_id, archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(no_web), host_gap_s=0)
    return store, ctx, group, parent


def runner(store, ctx) -> Runner:
    settings = store.settings()
    return Runner(store, ctx, Notifier(store, settings, telegram=ExplodingTelegram()), settings)


def notice(n: int, title: str, lang: str = "en") -> Item:
    return Item(external_id=f"n-{n}", url=f"https://example.test/notice/{n}", title=title,
                published=date.today(), doc_type="dhpc", lang=lang)


def process(r: Runner, item: Item) -> SourceStats:
    stats = SourceStats()
    r.process_item(SRC, MODULE, item, seed=False, stats=stats)
    return stats


def matches_of(store: MemoryStore, title: str) -> list[dict]:
    doc = next(d for d in store.document.values() if d["title_orig"] == title)
    return [m for m in store.match if m["document_id"] == doc["id"]]


def test_a_notice_naming_only_the_group_is_found_through_the_class_and_never_alerts(tmp_path):
    store, ctx, group, _ = profile(tmp_path)
    r = runner(store, ctx)
    stats = process(r, notice(1, "Fluoroquinolones: risk of tendon rupture and aortic aneurysm"))
    assert (stats.new, stats.matched, stats.alerts) == (1, 1, [])
    [m] = matches_of(store, "Fluoroquinolones: risk of tendon rupture and aortic aneurysm")
    assert m["class_id"] == group and m["ingredient_id"] is None and m["class_term_id"] is not None
    assert m["matched_text"] == "Fluoroquinolones"
    [issue] = store.issue.values()
    assert issue["class_only"] and not issue["is_backfill"]
    assert (issue["id"], "levo") in store.issue_ingredient   # filed under levofloxacin, for the daily digest


def test_a_notice_naming_the_ingredient_is_a_direct_finding(tmp_path):
    store, ctx, _, _ = profile(tmp_path)
    r = runner(store, ctx)
    stats = process(r, notice(2, "Levofloxacin 500 mg tablets: new warning"))
    assert (stats.new, stats.matched) == (1, 1)
    [m] = matches_of(store, "Levofloxacin 500 mg tablets: new warning")
    assert m["ingredient_id"] == "levo" and m["class_id"] is None and m["term_id"] == "t-levo"
    [issue] = store.issue.values()
    assert not issue["class_only"] and stats.alerts == [issue["id"]]


def test_the_parent_class_finds_nothing_until_it_is_switched_on(tmp_path):
    store, ctx, group, parent = profile(tmp_path)
    assert store.class_words("en") == {"levofloxacin": ["fluoroquinolone"]}   # what the literature watch searches
    assert store.rematch_due_terms()[1] == sorted(t.id for t in store.terms if t.class_id == group)
    r = runner(store, ctx)
    off_en = process(r, notice(3, "Quinolone antibiotics and QT prolongation"))
    off_ja = process(r, notice(4, "ニューキノロン系抗菌薬の添付文書改訂", lang="ja"))
    assert (off_en.matched, off_ja.matched, len(store.match)) == (0, 0, 0)

    store.set_class_search("levo", parent, True)
    assert store.class_words("en") == {"levofloxacin": ["fluoroquinolone", "quinolone antibiotic"]}
    assert set(store.rematch_due_terms()[1]) >= {t.id for t in store.terms if t.class_id == parent}
    r2 = runner(store, ctx)   # the next run loads the words
    on_en = process(r2, notice(5, "Quinolone antibiotics and QT prolongation (again)"))
    on_ja = process(r2, notice(6, "ニューキノロン系抗菌薬の添付文書改訂（再）", lang="ja"))
    assert (on_en.matched, on_ja.matched, on_en.alerts, on_ja.alerts) == (1, 1, [], [])
    assert {m["class_id"] for m in store.match} == {parent}
    assert all(i["class_only"] for i in store.issue.values())
    assert {g for _, g in store.issue_ingredient} == {"levo"}

    store.set_class_search("levo", parent, False)
    r3 = runner(store, ctx)
    assert process(r3, notice(7, "Quinolone antibiotics: once more")).matched == 0


def test_a_class_word_matches_only_in_its_own_language_and_never_inside_the_name(tmp_path):
    store, ctx, _, _ = profile(tmp_path)
    r = runner(store, ctx)
    assert process(r, notice(8, "Fluorchinolon-Antibiotika: Einschränkungen")).matched == 0    # German word, English notice
    assert process(r, notice(9, "Fluorchinolon-Antibiotika: Einschränkungen", lang="de")).matched == 1
    assert process(r, notice(10, "Fluoroquinolone antibiotics: reminder of disabling side effects")).matched == 1
    assert process(r, notice(11, "Levofloxacin-containing medicines")).matched == 1   # the stem catches endings
    assert process(r, notice(12, "Nothing of ours here")).matched == 0


def test_the_profile_is_derived_from_the_switches():
    store = MemoryStore()
    store.ingredient["levo"] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    store.drug_class["g"] = {"code": "J01MA", "name_en": "Fluoroquinolones", "origin": "atc", "wikidata_qid": None}
    store.drug_class["h"] = {"code": "RESP", "name_en": "Respiratory fluoroquinolones", "origin": "hand",
                             "wikidata_qid": None}
    store.link_ingredient_class("levo", "g")
    store.link_ingredient_class("levo", "h")   # a hand-made class linked without more is a manual group
    assert store.ingredient_class_state[("levo", "g")] == {"relation": "group", "enabled": True}
    assert store.ingredient_class_state[("levo", "h")] == {"relation": "manual", "enabled": True}
    store.link_ingredient_class("levo", "g", relation="parent", enabled=False)   # a link that exists never changes
    assert store.ingredient_class_state[("levo", "g")] == {"relation": "group", "enabled": True}
    with pytest.raises(KeyError):
        store.set_class_search("levo", "nowhere", True)
