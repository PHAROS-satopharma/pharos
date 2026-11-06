"""FDA's e-mail lists read from GovDelivery's public feeds (fda.gov refuses our servers). Each source is taken
from the catalogue (collectors/sources.yaml) as it runs; every fixture is the live feed saved on 6 Nov 2026.
Titles and dates are asserted exactly as published."""

from __future__ import annotations

from datetime import date

import pytest

from collectors.core.registry import load_catalogue
from collectors.parsers import feed
from collectors.parsers.base import ParseError
from tests.fakes_a2 import FakeCtx

_, SOURCES, _ = load_catalogue()
CATALOGUE = {s.id: s for s in SOURCES}
TOPIC = "https://public.govdelivery.com/topics/USFDA_{}/feed.rss"
FEEDS = {"fda-medwatch-gd": 190, "fda-druginfo-gd": 118, "fda-press-gd": 139, "fda-srlc-gd": 60}


def read(sid: str):
    n = FEEDS[sid]
    return feed.list_items(FakeCtx({TOPIC.format(n): f"fda-govdelivery/topic-{n}.rss"}), CATALOGUE[sid])


def test_the_four_feeds_are_switched_on_fda_sources():
    for sid, n in FEEDS.items():
        src = CATALOGUE[sid]
        assert src.enabled and src.regulator_id == "FDA" and src.channel == "rss", sid
        assert src.url == TOPIC.format(n) and src.parser == "feed", sid
        assert src.options["follow"] is False, sid          # the entry carries the whole bulletin
        assert "fda.gov" not in src.url, sid                 # fda.gov refuses our servers


@pytest.mark.parametrize("sid", list(FEEDS))
def test_every_bulletin_of_the_feed_is_kept_with_its_text(sid):
    items = read(sid)
    assert len(items) == 25 and len({i.external_id for i in items}) == 25
    assert all(i.url.startswith("https://content.govdelivery.com/accounts/USFDA/bulletins/") for i in items)
    assert all(i.published and i.lang == "en" for i in items)
    assert all(i.body_text and len(i.body_text) > 150 for i in items)    # a quiet week lists one medicine


def test_the_kybella_drug_safety_communication_is_read():
    items = read("fda-druginfo-gd")
    kybella = next(i for i in items if "Kybella" in i.title)
    assert kybella.title == ("FDA Approves Additional Information in Labeling for Kybella (Deoxycholic Acid) "
                             "Injection Warning of Adverse Reactions Associated with Unapproved Use")
    assert kybella.published == date(2026, 9, 16)
    assert kybella.url == "https://content.govdelivery.com/accounts/USFDA/bulletins/42af6f7"
    assert kybella.doc_type == "safety_update"
    assert "outside of the submental fat region" in kybella.body_text
    # an approval or a guidance is kept too, as "other": matching decides what concerns us
    assert {i.doc_type for i in items} == {"safety_update", "other"}


def test_medwatch_alerts_and_their_recalls():
    items = read("fda-medwatch-gd")
    first = items[0]
    assert first.title.startswith("FDA MedWatch - All Lots and Varieties of Tractor Wheels Organic Toddler")
    assert first.published == date(2026, 11, 4)
    assert "TOPIC:" in first.body_text and "Recall" in first.body_text
    argatroban = next(i for i in items if "Argatroban" in i.title)
    assert argatroban.published == date(2026, 10, 14)
    assert {i.doc_type for i in items} <= {"safety_alert", "recall", "safety_update"}


def test_press_releases_back_to_the_oldest_of_the_feed():
    items = read("fda-press-gd")
    assert items[0].title == ("FDA Grants Accelerated Approval to a New Treatment for Head and Neck "
                              "Squamous Cell Carcinoma")
    assert items[0].published == date(2026, 11, 5)
    assert min(i.published for i in items) == date(2026, 8, 27)


def test_the_labeling_changes_digest_lists_the_medicines():
    items = read("fda-srlc-gd")
    week = items[0]
    assert week.title == "CDER Drug Safety Labeling Changes 11/4/2026"
    assert week.published == date(2026, 11, 4) and week.doc_type == "label_change"
    assert "TALAZOPARIB TOSYLATE" in week.body_text and "HEPARIN SODIUM" in week.body_text


def test_a_page_that_is_not_a_feed_raises():
    ctx = FakeCtx({TOPIC.format(118): "ema-news/list.html"})
    with pytest.raises(ParseError):
        feed.list_items(ctx, CATALOGUE["fda-druginfo-gd"])
