"""PHAROS — MHRA read from GOV.UK's search API, not from the 20-entry Atom feeds (6 Nov 2026).

The Atom feeds hold only the newest 20 entries and cannot page: the Safety Roundups of November 2025 to June
2026 and the Class 4 levetiracetam defect notice of 1 October 2026 dropped off before a run read them, and a
backfill could not reach them. The search API lists every item. Fixtures saved from the live API on 6 Nov 2026
(medical_safety_alert, 1,465 items: the newest two pages; drug_safety_update: the newest page).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from collectors.core.registry import load_catalogue
from collectors.parsers import govuk
from collectors.parsers.base import ParseError
from tests.fakes_a2 import FakeCtx, fixture

_, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}
ALERTS, DSU = CFG["mhra-alerts"], CFG["mhra-dsu"]
LAST = b'{"results": [], "total": 1465}'


def routes(src=ALERTS, pages=("alerts-0", "alerts-100")) -> dict:
    out: dict = {govuk.search_url(src, k * govuk.PAGE): f"mhra-search/{p}.json" for k, p in enumerate(pages)}
    out["https://www.gov.uk/api/search.json*"] = LAST
    return out


def searched(ctx: FakeCtx) -> list[str]:
    return [u for m, u, _ in ctx.requests if m != "FORGET" and "/api/search.json" in u]


def rows(name: str) -> list[dict]:
    return json.loads(fixture(f"mhra-search/{name}.json"))["results"]


def test_both_mhra_sources_read_the_search_api_and_backfill_everything():
    for src, fmt in ((ALERTS, "medical_safety_alert"), (DSU, "drug_safety_update")):
        assert src.enabled and src.parser == "govuk" and govuk.is_search(src)
        assert "filter_organisations=medicines-and-healthcare-products-regulatory-agency" in src.url
        assert f"filter_format={fmt}" in src.url
        assert src.options.get("backfill_all") is True
    assert ALERTS.page_url == "https://www.gov.uk/drug-device-alerts"
    assert DSU.page_url == "https://www.gov.uk/drug-safety-update"


def test_a_first_read_takes_the_newest_page_with_its_types():
    ctx = FakeCtx(routes())
    items = [i for i in govuk.list_items(ctx, ALERTS) if not (i.structured or {}).get("roundup")]
    assert searched(ctx) == [govuk.search_url(ALERTS, 0)]
    assert len(items) == 100
    levetiracetam = next(i for i in items if "Levetiracetam Neuraxpharm" in i.title)
    assert levetiracetam.title.startswith("Class 4 Medicines Defect Notification: Neuraxpharm UK Limited")
    assert levetiracetam.doc_type == "recall" and levetiracetam.published == date(2026, 10, 1)
    assert levetiracetam.external_id.startswith("/drug-device-alerts/class-4-medicines-defect-notification")
    assert levetiracetam.url == "https://www.gov.uk" + levetiracetam.external_id
    roundups = [i for i in items if i.title.startswith("MHRA Safety Roundup")]
    assert len(roundups) == 9 and all(i.doc_type == "newsletter" for i in roundups)   # Feb to Oct 2026
    assert next(i for i in items if i.title.startswith("Field Safety Notices")).doc_type == "other"


def test_a_backfill_reads_the_whole_list():
    ctx = FakeCtx(routes(), backfill=True)
    items = [i for i in govuk.list_items(ctx, ALERTS) if not (i.structured or {}).get("roundup")]
    assert len(searched(ctx)) == 3 and len(items) == 200
    titles = {i.title for i in items}
    for month in ("November 2025", "December 2025", "January 2026", "June 2026"):
        assert f"MHRA Safety Roundup: {month}" in titles     # all lost by the Atom feed
    assert any(t.startswith("Class 4 Medicines Defect Notification: Levetiracetam Accord") for t in titles)
    assert len({i.external_id for i in items}) == 200


@pytest.mark.parametrize("last_ok,pages", [
    (datetime(2026, 1, 1, tzinfo=timezone.utc), 2),    # the newest page reaches back only to 25 Feb 2026
    (datetime(2026, 5, 1, tzinfo=timezone.utc), 1),
])
def test_a_run_reads_back_to_two_weeks_before_its_last_complete_read(last_ok, pages):
    ctx = FakeCtx(routes())
    ctx.last_ok_at = last_ok
    govuk.list_items(ctx, ALERTS)
    assert searched(ctx) == [govuk.search_url(ALERTS, k * govuk.PAGE) for k in range(pages)]


def test_drug_safety_updates_from_the_search_api():
    ctx = FakeCtx(routes(DSU, ("dsu-0",)))
    items = govuk.list_items(ctx, DSU)
    assert len(items) == 100 and all(i.doc_type == "safety_update" for i in items)
    assert items[0].title.startswith("Duvyzat")
    assert items[0].external_id.startswith("/drug-safety-update/")
    assert items[0].body_text and "Duchenne" in items[0].body_text


def test_a_search_api_shape_change_raises():
    for body in (b'{"error": "busy"}', b"<html>GOV.UK is down for maintenance</html>"):
        ctx = FakeCtx({govuk.search_url(ALERTS, 0): body})
        with pytest.raises(ParseError):
            govuk.list_items(ctx, ALERTS)


def test_search_item_skips_rows_without_a_path_or_title():
    assert govuk.search_item({"link": "https://elsewhere.example/x", "title": "x"}, ALERTS) is None
    assert govuk.search_item({"link": "/drug-device-alerts/x", "title": " "}, ALERTS) is None
    row = rows("alerts-0")[0]
    assert govuk.search_item(row, ALERTS).external_id == row["link"]
