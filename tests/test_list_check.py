"""The weekly list check (collectors/completeness.py): every source's own list against what PHAROS holds."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from collectors import completeness
from collectors.core.memstore import MemoryStore
from collectors.core.models import Item, SourceConfig
from collectors.parsers import base as parser_base


def src(sid: str = "t-alerts", **kw) -> SourceConfig:
    base = dict(id=sid, regulator_id="T", kind="safety", channel="html", url=f"https://x.test/{sid}",
                parser="fake", languages=["en"], schedule="4h", enabled=True, options={}, expected_max_gap_days=30)
    return SourceConfig(**{**base, **kw})


def item(eid: str, days_ago: int | None = 10, title: str | None = None) -> Item:
    return Item(external_id=eid, url=f"https://x.test/{eid}", title=title or f"Notice {eid}",
                published=date.today() - timedelta(days=days_ago) if days_ago is not None else None,
                doc_type="dhpc", lang="en")


class Ctx(SimpleNamespace):
    pass


def module(items: list[Item], *, broken: list[str] = (), drop: list[str] = (), fails: bool = False,
           aliases=None):
    def list_items(ctx, _src):
        if fails:
            raise TimeoutError("the list did not answer")
        ctx.list_errors.extend(broken)
        for title in drop:
            parser_base.dropped(title, "category: veterinary")
        return list(items)

    m = SimpleNamespace(list_items=list_items)
    if aliases:
        m.aliases = aliases
    return m


def store_with(stored: dict[str, set[str]]) -> MemoryStore:
    s = MemoryStore()
    s.known_external_ids = lambda sid: set(stored.get(sid, set()))
    return s


def test_a_listed_notice_that_is_not_stored_is_named_and_an_old_one_is_not_missing():
    s = store_with({"t-alerts": {"a1", "a2"}})
    items = [item("a1"), item("a2"), item("a3", 3, "Recall: batch 7"), item("a4", 365 * 5), item("a1")]
    rows = completeness.run(s, Ctx(), sources=[src()], loader=lambda _p: module(items))
    r = rows[0]
    assert (r["listed"], r["stored"], r["older"], r["missing"], r["complete"]) == (4, 2, 1, 1, True)
    assert r["missing_items"] == [{"external_id": "a3", "title": "Recall: batch 7", "url": "https://x.test/a3",
                                   "published": (date.today() - timedelta(days=3)).isoformat()}]
    assert s.list_check == rows


def test_a_source_that_keeps_all_its_history_counts_an_old_notice_as_missing():
    s = store_with({})
    rows = completeness.run(s, Ctx(), sources=[src(options={"backfill_all": True})],
                            loader=lambda _p: module([item("old", 365 * 5)]))
    assert (rows[0]["older"], rows[0]["missing"]) == (0, 1)


def test_a_notice_stored_under_another_id_is_stored_and_filtered_ones_are_counted_apart():
    s = store_with({"t-alerts": {"PMC9"}})
    m = module([item("p1")], drop=["Veterinary letter", "Press release"], aliases=lambda it: ["PMC9"])
    r = completeness.run(s, Ctx(), sources=[src()], loader=lambda _p: m)[0]
    assert (r["stored"], r["missing"], r["filtered"]) == (1, 0, 2)
    assert parser_base.DROPPED == [] and parser_base.WATCHED is None     # nothing left for the next source


def test_a_list_read_in_part_or_not_at_all_is_never_taken_as_complete():
    s = store_with({"t-alerts": {"a1"}})
    part = completeness.run(s, Ctx(), sources=[src()],
                            loader=lambda _p: module([item("a1")], broken=["page 3: HTTP 503"]))[0]
    assert part["complete"] is False and "page 3: HTTP 503" in part["error"]
    none = completeness.run(s, Ctx(), sources=[src("t-b")], loader=lambda _p: module([], fails=True))[0]
    assert none["complete"] is False and "TimeoutError" in none["error"] and none["listed"] == 0


def test_mailboxes_literature_label_databases_and_switched_off_sources_are_not_checked():
    s = store_with({})
    sources = [src("t-mail", channel="email"), src("t-lit", kind="literature"), src("t-spc", kind="spc"),
               src("t-off", enabled=False), src("t-on")]
    rows = completeness.run(s, Ctx(), sources=sources, loader=lambda _p: module([item("a1")]))
    assert [r["source_id"] for r in rows] == ["t-on"]


def test_sources_left_when_the_time_runs_out_say_so():
    s = store_with({})
    ticks = iter([0, 0, 10_000, 10_000])
    rows = completeness.run(s, Ctx(), sources=[src("t-a"), src("t-b")], loader=lambda _p: module([item("a1")]),
                            clock=lambda: next(ticks), budget_s=60)
    assert rows[0]["complete"] is True
    assert rows[1]["complete"] is False and "out of time" in rows[1]["error"]
