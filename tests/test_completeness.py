"""PHAROS — nothing leaves a source unseen (6 Nov 2026): a keyword filter never drops a notice that names a
watched ingredient, every drop is kept with why, and a list that has moved past everything stored is an alert."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from collectors.core.models import Item
from collectors.matching import Matcher, Term
from collectors.parsers import base
from collectors.parsers.feed import parse_feed
from collectors.run import possible_gap
from tests.fakes_a2 import source


@pytest.fixture()
def watching():
    m = Matcher([Term(id="t", term="paracetamol", lang="en", ingredient_id="ing-para"),
                 Term(id="c", term="nsaid", lang="en", class_id="cls", kind="class")])
    base.WATCHED = lambda text: any(h.term.ingredient_id for h in m.match_text(text, "title"))
    base.DROPPED.clear()
    yield
    base.WATCHED = None
    base.DROPPED.clear()


def test_a_keyword_filter_keeps_a_notice_naming_a_watched_ingredient(watching):
    include = ["safety"]
    assert base.keyword_ok("Paracetamol and pregnancy: new advice", include)        # no keyword, but named
    assert not base.keyword_ok("New chair of the agency board", include)
    assert not base.keyword_ok("NSAID class review", include)                      # a class word is not enough
    assert base.keyword_ok("Safety of paracetamol\nmore", None, ["safety"])      # excluded word, but named
    assert base.DROPPED == [("New chair of the agency board", "keywords: none of safety"),
                            ("NSAID class review", "keywords: none of safety")]


def test_without_a_watchlist_filters_drop_as_before_and_note_why():
    base.WATCHED = None
    base.DROPPED.clear()
    assert not base.keyword_ok("Veterinary: enrofloxacin", None, ["veterinary"])
    assert base.DROPPED == [("Veterinary: enrofloxacin", "keyword: veterinary")]
    base.DROPPED.clear()


def test_a_feed_category_drop_is_noted_and_a_watched_name_keeps_it(watching):
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
      <item><title>Press release: paracetamol campaign</title><link>https://x.test/1</link><category>Press</category></item>
      <item><title>Press release: new building</title><link>https://x.test/2</link><category>Press</category></item>
      <item><title>Recall of a batch</title><link>https://x.test/3</link><category>Recall</category></item>
    </channel></rss>"""
    src = source("x-feed", "https://x.test/rss", parser="feed", channel="rss", doc_type="safety_alert",
                 include_categories=["Recall"])
    titles = [i.title for i in parse_feed(rss, src, src.url)]
    assert titles == ["Press release: paracetamol campaign", "Recall of a batch"]
    assert [d[0] for d in base.DROPPED] == ["Press release: new building"]
    assert base.DROPPED[0][1].startswith("categories: Press")


def _items(*days: str) -> list[Item]:
    return [Item(external_id=f"n{k}", url=f"https://x.test/{k}", title=f"n{k}",
                 published=date.fromisoformat(d), doc_type="safety_alert", lang="en") for k, d in enumerate(days)]


def test_a_list_that_moved_past_everything_stored_is_a_possible_gap():
    src = source("mhra-alerts", "https://x.test/feed", channel="atom")
    prev = {"last_item_at": datetime(2026, 6, 1, tzinfo=timezone.utc)}
    items = _items("2026-11-01", "2026-10-15", "2026-09-30")
    gap = possible_gap(src, items, {"old-1", "old-2"}, prev)
    assert gap and "30 Sep 2026" in gap and "01 Jun 2026" in gap
    # one item already stored: the list overlaps, nothing was missed
    assert possible_gap(src, items, {"n2"}, prev) is None
    # the oldest listed is no newer than the newest stored: no gap
    assert possible_gap(src, _items("2026-11-01", "2026-06-01", "2026-05-30"), {"old"}, prev) is None
    # a first read, a mailbox, literature and an opted-out source are never a gap
    assert possible_gap(src, items, set(), prev) is None
    assert possible_gap(source("m", "imap://x", channel="email"), items, {"old"}, prev) is None
    assert possible_gap(source("p", "https://x.test", kind="literature"), items, {"old"}, prev) is None
    assert possible_gap(source("o", "https://x.test", gap_check=False), items, {"old"}, prev) is None
