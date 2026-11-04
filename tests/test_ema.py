"""EMA DHPC and PSUSA parsers against EMA's real JSON data files and a real DHPC page."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from collectors.core.memstore import MemoryStore
from collectors.core.models import Fetched
from collectors.core.registry import load_catalogue
from collectors.matching import Matcher
from collectors.parsers import ema_dhpc, ema_psusa
from collectors.parsers.base import ParseError

FIX = Path(__file__).resolve().parent / "fixtures"
_, SOURCES, _ = load_catalogue()
CFG = {s.id: s for s in SOURCES}


def load(rel: str) -> dict:
    return json.loads((FIX / rel).read_text(encoding="utf-8"))


class PageCtx:
    """Serves one saved page for one URL; any other URL is a test failure."""

    def __init__(self, url: str, rel: str, content_type: str = "text/html; charset=utf-8") -> None:
        self.url, self.rel, self.content_type = url, rel, content_type
        self.calls: list[str] = []

    def get(self, url: str, **_: object) -> Fetched:
        self.calls.append(url)
        assert url == self.url, url
        return Fetched(status=200, final_url=url, content=(FIX / self.rel).read_bytes(),
                       content_type=self.content_type)


# ───────────────────────────── DHPC ─────────────────────────────

def test_dhpc_rows():
    data = load("ema-dhpc/dhpc-output-json-report_en.json")
    items = ema_dhpc.parse_rows(data, CFG["ema-dhpc"])
    human = [r for r in data["data"] if r["category"] == "Human"]
    assert len(items) == len(human) == 172            # the 4 veterinary rows are dropped
    first = items[0]
    assert first.url == first.external_id == "https://www.ema.europa.eu/en/medicines/dhpc/respreeza-1"
    assert first.title == "Respreeza - direct healthcare professional communication (DHPC)"
    assert first.published == date(2026, 11, 4)        # dissemination_date 04/11/2026 (d/m/Y)
    assert first.doc_type == "dhpc" and first.lang == "en"
    assert first.structured["active_substances_list"] == ["human alpha1-proteinase inhibitor"]
    assert first.structured["dhpc_type"] == "Quality defect"
    assert len({i.external_id for i in items}) == len(items)


def test_dhpc_page_gives_text_and_pdf():
    data = load("ema-dhpc/dhpc-output-json-report_en.json")
    item = ema_dhpc.parse_rows(data, CFG["ema-dhpc"])[0]
    ctx = PageCtx(item.url, "ema-dhpc/respreeza-1.html")
    ema_dhpc.fetch_detail(ctx, CFG["ema-dhpc"], item)
    assert ctx.calls == [item.url]
    assert item.attachment_urls == ["https://www.ema.europa.eu/en/media/75906"]
    assert item.body_text and "Respreeza" in item.body_text


def test_dhpc_shape_change_raises():
    with pytest.raises(ParseError):
        ema_dhpc.parse_rows({"data": [{"title": "x"}]}, CFG["ema-dhpc"])
    with pytest.raises(ParseError):
        ema_dhpc.parse_rows({"rows": []}, CFG["ema-dhpc"])


def test_split_list():
    assert ema_dhpc.split_list("a; b;;\nc ") == ["a", "b", "c"]
    assert ema_dhpc.split_list(None) == []


# ───────────────────────────── PSUSA ─────────────────────────────

def test_psusa_rows_and_lornoxicam():
    data = load("ema-psusa/psusa-slice.json")
    items = ema_psusa.parse_rows(data, CFG["ema-psusa"])
    assert len(items) == 9                              # the meloxicam row has no category
    lorno = next(i for i in items if i.external_id == "PSUSA/00001911/202412")
    assert lorno.title == "lornoxicam: PSUSA/00001911/202412 (Maintenance)"
    assert lorno.published == date(2025, 7, 29)
    assert lorno.doc_type == "psusa"
    assert lorno.url == "https://www.ema.europa.eu/en/medicines/psusa/psusa-00001911-202412"
    assert lorno.structured["procedure_numbers"] == ["PSUSA/00001911/202412"]
    multi = next(i for i in items if i.external_id == "PSUSA/00000910/202603")
    assert multi.structured["active_substances_list"] == ["cystine", "pyridoxine hydrochloride"]


def test_psusa_structured_match_is_lornoxicam_only():
    store = MemoryStore()
    store.load_seed()
    matcher = Matcher(store.load_terms())
    items = {i.external_id: i for i in ema_psusa.parse_rows(load("ema-psusa/psusa-slice.json"),
                                                            CFG["ema-psusa"])}
    hits = matcher.match_structured(items["PSUSA/00001911/202412"].structured,
                                    ema_psusa.STRUCTURED_FIELDS)
    assert hits and all(h.confidence == "high" and h.field == "structured" for h in hits)
    for other in ("PSUSA/00002893/202602", "PSUSA/00002438/202304"):  # tenoxicam, piroxicam
        found = matcher.match_structured(items[other].structured, ema_psusa.STRUCTURED_FIELDS)
        assert not [h for h in found if h.term.ingredient_id]


def test_psusa_detail_only_on_ema():
    item = ema_psusa.parse_rows(load("ema-psusa/psusa-slice.json"), CFG["ema-psusa"])[0]
    item.url = "https://example.org/elsewhere"

    class NoNetwork:
        def get(self, *a, **k):
            raise AssertionError("must not fetch outside ema.europa.eu")

    assert ema_psusa.fetch_detail(NoNetwork(), CFG["ema-psusa"], item) is item
