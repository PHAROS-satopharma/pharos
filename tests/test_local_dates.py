"""PHAROS — Japanese era dates and the Romance-language month abbreviations.

PMDA (and other Japanese pages) may write 令和7年10月1日 instead of 2025年10月1日; before this an
era-dated row was not even recognised as a date row and was dropped without a word.
"""

from __future__ import annotations

from datetime import date

import pytest

from collectors.parsers import pmda
from collectors.parsers._html_util import local_date
from collectors.parsers.base import parse_date
from tests.fakes_a2 import fixture, source

# ───────────────────────────── Japanese era ─────────────────────────────


@pytest.mark.parametrize("text,expected", [
    ("令和7年10月1日", date(2025, 10, 1)),
    ("令和元年5月1日", date(2019, 5, 1)),
    ("令和 8 年 10 月 27 日", date(2026, 10, 27)),
    ("平成31年4月30日", date(2019, 4, 30)),
    ("平成元年1月8日", date(1989, 1, 8)),
    ("発出日：令和7年10月1日（火）", date(2025, 10, 1)),
    ("R7.10.1", date(2025, 10, 1)),
    ("H31.4.30", date(2019, 4, 30)),
])
def test_era_dates_in_the_shared_parser(text, expected):
    assert parse_date(text) == expected
    assert local_date(text, "ja") == expected


def test_era_year_and_month_is_the_first():
    assert local_date("令和8年4月", "ja") == date(2026, 4, 1)


def test_short_era_form_never_beats_a_gregorian_date():
    # "VR7.10.1" (a version string) is not an era date.
    assert local_date("VR7.10.1", "ja") is None
    assert parse_date("Release R5.3.1, 12/03/2026") == date(2026, 3, 12)
    assert local_date("Release R5.3.1, 12/03/2026", "ja") == date(2026, 3, 12)
    assert local_date("R7.10.1", "en") is None          # the short form is read on Japanese pages


def _era(rel: str) -> bytes:
    """The real PMDA fixture with every Gregorian 2026年 rewritten as 令和8年 (2026 = 令和8)."""
    return fixture(rel).decode("utf-8").replace("2026年", "令和8年").encode("utf-8")


PMDA_REV = ("https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/"
            "revision-of-precautions/")


def test_pmda_revisions_era_dated_rows_are_kept():
    src = source("pmda-revisions", PMDA_REV + "0001.html", languages=["ja"])
    gregorian = pmda.parse_revisions(fixture("pmda-revisions/fy2026.html"), PMDA_REV + "0375.html",
                                     src)
    era = pmda.parse_revisions(_era("pmda-revisions/fy2026.html"), PMDA_REV + "0375.html", src)
    assert [i.external_id for i in era] == [i.external_id for i in gregorian]
    assert [i.published for i in era] == [i.published for i in gregorian]
    first = era[0]
    assert first.title == "インクリシランナトリウム"
    assert first.published == date(2026, 10, 27)
    assert "https://www.pmda.go.jp/files/000283214.pdf" in first.attachment_urls  # MHLW notice


def test_pmda_urgent_era_dated_rows_are_kept():
    src = source("pmda-urgent", "https://www.pmda.go.jp/x/esc-rsc/0001.html", languages=["ja"])
    items = pmda.parse_urgent(_era("pmda-urgent/list.html"), "https://www.pmda.go.jp/", src)
    assert items and items[0].published == date(2026, 5, 21)


def test_pmda_msi_era_month():
    src = source("pmda-msi", "https://www.pmda.go.jp/x/0001.html", languages=["ja"])
    items = pmda.parse_msi(_era("pmda-msi/list.html"), "https://www.pmda.go.jp/", src)
    assert items[0].published == date(2026, 4, 1)


# ───────────────────────────── month abbreviations ─────────────────────────────


@pytest.mark.parametrize("text,lang,expected", [
    # Italian
    ("12 gen 2026", "it", date(2026, 1, 12)),
    ("3 mag 2026", "it", date(2026, 5, 3)),
    ("3 giu. 2026", "it", date(2026, 6, 3)),
    ("3 lug 2026", "it", date(2026, 7, 3)),
    ("3 ago 2026", "it", date(2026, 8, 3)),
    ("3 set 2026", "it", date(2026, 9, 3)),
    ("12 ott 2026", "it", date(2026, 10, 12)),
    ("1 DIC 2026", "it", date(2026, 12, 1)),
    # Spanish
    ("5 ene 2026", "es", date(2026, 1, 5)),
    ("5 abr. 2026", "es", date(2026, 4, 5)),
    ("5 ago 2026", "es", date(2026, 8, 5)),
    ("5 sept 2026", "es", date(2026, 9, 5)),
    ("5 dic 2026", "es", date(2026, 12, 5)),
    # Portuguese
    ("7 fev 2026", "pt", date(2026, 2, 7)),
    ("7 abr 2026", "pt", date(2026, 4, 7)),
    ("7 set 2026", "pt", date(2026, 9, 7)),
    ("7 out. 2026", "pt-PT", date(2026, 10, 7)),
    ("7 dez 2026", "pt", date(2026, 12, 7)),
    ("out 2026", "pt", date(2026, 10, 1)),
    # French
    ("3 févr. 2026", "fr", date(2026, 2, 3)),
    ("3 avr. 2026", "fr", date(2026, 4, 3)),
    ("3 juil. 2026", "fr", date(2026, 7, 3)),
    ("3 Déc. 2026", "fr", date(2026, 12, 3)),
])
def test_romance_month_abbreviations(text, lang, expected):
    assert local_date(text, lang) == expected


@pytest.mark.parametrize("text", ["carried out 2026", "set 2026", "2 ago 2026"])
def test_english_words_are_not_months_on_an_english_page(text):
    assert local_date(text, "en") is None
