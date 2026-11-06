"""FDA adverse-event report counts (collectors/faers.py, migration 0071), with a fake openFDA: no network."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date

import pytest

from collectors import faers
from collectors.faers import OpenFda, OpenFdaError, disproportion


# ───────────────────────────── the arithmetic, worked by hand ─────────────────────────────
def test_prr_ror_and_chi_squared_worked_by_hand():
    # a=10 of 100 reports of the ingredient, c=100 of 9,900 of every other drug.
    # PRR = 0.1 / (100/9900) = 9.9; ln-SE = sqrt(1/10 - 1/100 + 1/100 - 1/9900) = 0.316068 -> 5.328 to 18.394
    # ROR = 10*9800 / (90*100) = 10.889; ln-SE = sqrt(1/10 + 1/90 + 1/100 + 1/9800) = 0.348157 -> 5.503 to 21.544
    # chi2 = 10000 * (|98000 - 9000| - 5000)^2 / (100 * 9900 * 110 * 9890) = 65.514
    got = disproportion(10, 90, 100, 9800)
    assert got.prr == pytest.approx(9.9)
    assert (got.prr_low, got.prr_high) == (pytest.approx(5.3284, abs=1e-4), pytest.approx(18.3939, abs=1e-4))
    assert got.ror == pytest.approx(10.8889, abs=1e-4)
    assert (got.ror_low, got.ror_high) == (pytest.approx(5.5034, abs=1e-4), pytest.approx(21.5444, abs=1e-4))
    assert got.chi2 == pytest.approx(65.514, abs=1e-3)


def test_yates_chi_squared_with_few_reports():
    # 3 reports and PRR = 0.3 / (10/990) = 29.7; Yates' chi2 = 1000 * (|3*980 - 7*10| - 500)^2 / (10*990*13*987)
    # = 1000 * 2370^2 / 127,026,900 = 44.2
    got = disproportion(3, 7, 10, 980)
    assert got.prr == pytest.approx(29.7) and got.chi2 == pytest.approx(44.218, abs=1e-3)
    assert disproportion(3, 97, 150, 9750).prr == pytest.approx(1.98)


def r(reports: int, prr: float | None, low: float | None) -> dict:
    return {"reports": reports, "prr": prr, "prr_low": low}


def test_the_flag_is_an_outlier_in_the_ingredients_own_profile():
    # Evans' criteria (3 reports, PRR 2, chi-squared 4) flagged 88 of paracetamol's 100 most reported reactions on
    # 6 Nov 2026: its reports name more reactions than FDA's average report, so fatigue, nausea and headache all
    # passed. The flag now asks how far a reaction stands out from the ingredient's own reactions.
    rows = [r(7370, 2.0, 1.95), r(6906, 2.1, 2.05), r(6509, 2.2, 2.1), r(5000, 2.4, 2.3), r(4000, 2.5, 2.4),
            r(10, 6.0, 4.0),       # median PRR 2.5: twice is 5; 6.0 with its interval above 2 stands out
            r(3, 9.0, 1.5),        # high, but its interval reaches below 2
            r(2, 30.0, 8.0),       # 2 reports only
            r(4, None, None)]      # no other drug has it: counted as the highest PRR, and it stands out
    assert faers.outliers(rows) == [False, False, False, False, False, True, False, False, True]
    assert faers.outliers([]) == []


def test_the_outlier_bar_is_twice_the_median_inclusive():
    # median 2.0: a PRR of exactly 4.0 is flagged, 3.99 is not; a lower bound of exactly 2 is enough
    assert faers.outliers([r(9, 2.0, 1.0), r(9, 2.0, 1.0), r(3, 4.0, 2.0)]) == [False, False, True]
    assert faers.outliers([r(9, 2.0, 1.0), r(9, 2.0, 1.0), r(3, 3.99, 2.5)]) == [False, False, False]
    # an even number of reactions: the median is the mean of the middle two (2 and 4 -> 3, the bar 6)
    assert faers.outliers([r(9, 1.0, 0.5), r(9, 2.0, 1.0), r(9, 4.0, 3.0), r(9, 6.0, 5.0)]) == [False] * 3 + [True]


def test_zero_cells_give_none_never_a_division_by_zero():
    none = disproportion(0, 100, 50, 9850)           # the ingredient never has the reaction
    assert none.prr == 0 and none.ror == 0 and none.prr_low is None and none.ror_low is None
    assert none.chi2 == 0                            # |0 - 5000| - 10000/2 = 0
    only = disproportion(4, 96, 0, 9900)             # no other drug has it: PRR and ROR are infinite
    assert only.prr is None and only.ror is None and only.chi2 > 4
    every = disproportion(5, 0, 20, 975)             # every report of the ingredient has it: ROR divides by b = 0
    assert every.prr == pytest.approx(49.75) and every.ror is None and every.prr_low is not None
    nothing = disproportion(0, 0, 0, 0)
    assert asdict(nothing) == {"prr": None, "prr_low": None, "prr_high": None, "ror": None, "ror_low": None,
                               "ror_high": None, "chi2": None}
    with pytest.raises(ValueError):
        disproportion(-1, 1, 1, 1)


# ───────────────────────────── quarters and the search ─────────────────────────────
def test_the_last_eight_complete_quarters():
    full = faers.last_quarters(date(2026, 9, 30))
    assert full[0] == date(2024, 10, 1) and full[-1] == date(2026, 7, 1) and len(full) == 8
    assert faers.last_quarters(date(2026, 9, 29))[-1] == date(2026, 4, 1)       # September not complete yet
    assert faers.quarter_end(date(2026, 10, 1)) == date(2026, 12, 31)
    assert faers.previous_quarter(date(2026, 1, 1)) == date(2025, 10, 1)


def test_the_inn_is_searched_exactly_in_three_fields():
    s = faers.name_search(' carvedilol "x" ')
    assert s == ('(patient.drug.openfda.generic_name.exact:"CARVEDILOL X" '
                 'patient.drug.openfda.substance_name.exact:"CARVEDILOL X" '
                 'patient.drug.activesubstance.activesubstancename.exact:"CARVEDILOL X")')


def test_a_us_name_that_differs_from_the_inn_is_searched_with_it():
    # FDA files paracetamol as ACETAMINOPHEN (RxNorm's ingredient name): searching the INN alone found 0 reports
    s = faers.name_search("paracetamol", "Acetaminophen")
    for field in faers.NAME_FIELDS:
        assert f'{field}:"PARACETAMOL"' in s and f'{field}:"ACETAMINOPHEN"' in s
    assert s.startswith("(") and s.endswith(")") and s.count(":") == 6
    assert faers.name_search("carvedilol", "CARVEDILOL") == faers.name_search("carvedilol")     # the same name once


# ───────────────────────────── a fake openFDA ─────────────────────────────
QUARTER_DAYS = ["20241001", "20250110", "20250401", "20250701", "20251001", "20260101", "20260401", "20260930"]
WHOLE = "receivedate:[20241001 TO 20260930]"
Q3 = "receivedate:[20260701 TO 20260930]"
Q1 = "receivedate:[20250101 TO 20250331]"


def counted(rows: dict[str, int], key: str = "term") -> dict:
    return {"results": [{key: k, "count": v} for k, v in rows.items()]}


class FakeFda:
    """Every drug: 10,000 reports a quarter. Codamine: 80 reports in Jan–Mar 2025 and 120 in Jul–Sep 2026."""

    def __init__(self, broken: str = "BROKENINE"):
        self.asked: list[dict] = []
        self.broken = broken

    def __call__(self, params: dict[str, str]):
        self.asked.append(dict(params))
        s, count = params.get("search", ""), params.get("count")
        if self.broken in s:
            return 400, {"error": {"code": "BAD_REQUEST", "message": "Syntax error"}}
        if "NOTHINGINE" in s:
            return 404, {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}
        if count == faers.DRUG:
            if '"RARE THING"' in s:     # the drugs named with a reaction: itself and its salt, then the others
                return 200, counted({"CODAMINE": 3, "CODAMINE HYDROCHLORIDE": 3, "BACKGROUNDOL": 3, "PARTNERINE": 3,
                                     "OTHERAMINE": 2})
            # the drugs named in all its reports: a full list of 100
            rows = {f"FILLDRUG {i:03}": 5 for i in range(96)}
            return 200, counted({"CODAMINE": 200, "CODAMINE HYDROCHLORIDE": 50, "BACKGROUNDOL": 120, "PARTNERINE": 6,
                                 **rows})
        if count == faers.AGE:      # the rare thing's 3 reports: one woman of 61 or 62, reported three times
            assert f"{faers.AGE_UNIT}:801" in s and '"RARE THING"' in s
            return 200, counted({"61": 2, "62": 1, "1": 9})
        if count == faers.SEX:
            assert f"{faers.AGE}:[60 TO 62]" in s
            return 200, counted({"2": 3})
        drug = "CODAMINE" in s
        if count == "receivedate":
            return 200, counted({"20250110": 80, "20260815": 120} if drug else {d: 10000 for d in QUARTER_DAYS},
                                key="time")
        if count == faers.REACTION:
            if drug and WHOLE in s:
                return 200, counted({"NAUSEA": 12, "HEPATITIS": 30, "RARE THING": 3})
            if drug and Q3 in s:
                return 200, counted({"HEPATITIS": 20, "NAUSEA": 12})
            if drug and Q1 in s:
                return 200, counted({"HEPATITIS": 10, "RARE THING": 3})
            if WHOLE in s:      # every drug: a full list of 100, so a reaction not in it is searched alone
                rows = {f"FILLER {i:03}": 5000 - i for i in range(98)}
                return 200, counted({**rows, "NAUSEA": 4000, "HEPATITIS": 300})
            return 200, counted({"HEPATITIS": 40, "NAUSEA": 250})
        if params.get("limit") == "1" and '"RARE THING"' in s:
            return 200, {"meta": {"results": {"total": 6}}, "results": [{}]}
        raise AssertionError(f"not expected: {params}")


def api_for(fake, key=None, sleeps=None):
    t = iter(range(0, 10**6, 100))                    # the clock moves on: no pacing wait in the tests
    return OpenFda(fake, key, sleep=(sleeps.append if sleeps is not None else lambda s: None), clock=lambda: next(t))


def test_one_ingredient_counted_with_its_quarters_and_its_table():
    fake = FakeFda()
    api = api_for(fake)
    bg = faers.Background(api, today=date(2026, 11, 6))
    assert bg.quarters[0] == date(2024, 10, 1) and bg.quarters[-1] == date(2026, 7, 1)
    got = faers.count_ingredient(api, bg, "Codamine")
    assert (got["searched"], got["reports"], got["all_reports"]) == ("CODAMINE", 200, 80000)
    assert (got["first_quarter"], got["last_quarter"]) == ("2024-10-01", "2026-07-01")
    assert [q["reports"] for q in got["quarters"]] == [0, 80, 0, 0, 0, 0, 0, 120]
    assert all(q["complete"] and q["all_reports"] == 10000 for q in got["quarters"])
    by = {r["reaction"]: r for r in got["reactions"]}
    assert list(by) == ["HEPATITIS", "NAUSEA", "RARE THING"]              # most reported first
    # hepatitis: a=30, b=200-30, c=300-30, d=80000-200-270
    assert by["HEPATITIS"] == {"reaction": "HEPATITIS", "reports": 30, "all_reports": 300,
                               **asdict(disproportion(30, 170, 270, 79530)), "flagged": False,
                               "co_drug": None, "co_reports": None, "co_all_reports": None,
                               "series_reports": None, "series_age": None, "series_sex": None}
    # PRRs: hepatitis 44.3, nausea 1.2, rare thing 399 (3 of its 200 reports, 3 more among every other drug's
    # 79,800): the median is 44.3, so only the rare thing is at least twice it
    assert by["RARE THING"]["flagged"] and not by["HEPATITIS"]["flagged"] and not by["NAUSEA"]["flagged"]
    assert by["RARE THING"]["all_reports"] == 6                           # searched alone: not in every drug's 100
    assert sorted((c["quarter"], c["reaction"], c["reports"], c["all_reports"]) for c in got["counts"]) == [
        ("2025-01-01", "HEPATITIS", 10, 40), ("2025-01-01", "RARE THING", 3, 0),
        ("2026-07-01", "HEPATITIS", 20, 40), ("2026-07-01", "NAUSEA", 12, 250)]
    # 1 for every drug's days; the ingredient's days, whole period and its 2 quarters with reports; every drug's
    # whole period and those 2 quarters; 1 reaction alone; the drugs named with the 1 flagged reaction, and in all
    # the ingredient's reports; its patients' ages, and the sexes of the largest group
    assert api.requests == 13
    faers.count_ingredient(api, bg, "Codamine")
    assert api.requests == 21                                            # every drug's counts are asked once a run
    assert all(p["limit"] == "100" for p in fake.asked if p.get("count") == faers.REACTION)


def test_a_reaction_openfda_cannot_search_is_counted_by_its_words():
    # FDA writes an apostrophe as ^ ("WERNICKE^S ENCEPHALOPATHY") and openFDA's search refuses a ^ even in quotes
    # (HTTP 400 "Search not supported", 6 Nov 2026), which failed lornoxicam's whole count. The phrase on the
    # analysed field finds the reports (152 on 6 Nov), and their count by exact reaction gives this one's.
    asked: list[dict] = []

    def get(params):
        asked.append(dict(params))
        s, count = params.get("search", ""), params.get("count")
        if count == "receivedate":
            return 200, counted({d: 10000 for d in QUARTER_DAYS}, key="time")
        if params.get("limit") == "1":
            if "^" in s:
                return 400, {"error": {"code": "BAD_REQUEST", "message": f"Search not supported: {s}"}}
            return 200, {"meta": {"results": {"total": 6}}, "results": [{}]}
        if count == faers.REACTION and s == WHOLE:
            return 200, counted({f"FILLER {i:03}": 5000 - i for i in range(100)})
        if count == faers.REACTION and s == f'patient.reaction.reactionmeddrapt:"WERNICKE S ENCEPHALOPATHY" AND {WHOLE}':
            return 200, counted({"WERNICKE^S ENCEPHALOPATHY": 152, "CONFUSIONAL STATE": 40})
        raise AssertionError(f"not expected: {params}")

    bg = faers.Background(api_for(get), today=date(2026, 11, 6))
    assert bg.whole_count("WERNICKE^S ENCEPHALOPATHY") == 152
    assert bg.whole_count("RARE THING") == 6                         # every other reaction: searched exactly
    assert bg.whole_count("WERNICKE^S ENCEPHALOPATHY") == 152 and len(asked) == 5     # asked once a run


def test_a_flagged_reaction_names_the_drug_most_reported_with_it():
    fake = FakeFda()
    api = api_for(fake)
    got = faers.count_ingredient(api, faers.Background(api, today=date(2026, 11, 6)), "Codamine")
    by = {r["reaction"]: r for r in got["reactions"]}
    # its salt is reported as often, but it is the ingredient itself; BACKGROUNDOL too, but it is in 120 of
    # Codamine's 200 reports: in all 3 of these is less than twice that share. PARTNERINE is in 6 of the 200.
    assert by["RARE THING"]["flagged"] and (
        by["RARE THING"]["co_drug"], by["RARE THING"]["co_reports"], by["RARE THING"]["co_all_reports"]) == (
        "PARTNERINE", 3, 6)
    # not flagged: no drug is looked up for it
    for name in ("HEPATITIS", "NAUSEA"):
        r = by[name]
        assert not r["flagged"] and r["co_drug"] is None and r["co_reports"] is None and r["co_all_reports"] is None
    asked = [p for p in fake.asked if p.get("count") == faers.DRUG]
    assert len(asked) == 2 and all(WHOLE in p["search"] and faers.name_search("Codamine") in p["search"] for p in asked)
    assert 'patient.reaction.reactionmeddrapt.exact:"RARE THING"' in asked[0]["search"] and asked[0]["limit"] == "25"
    assert "reactionmeddrapt" not in asked[1]["search"] and asked[1]["limit"] == "100"


def test_the_drug_shown_with_a_reaction_is_over_represented_and_never_the_ingredient():
    asked: list[dict] = []

    def get(params):
        asked.append(dict(params))
        s = params["search"]
        if "WERNICKE" in s:
            return 400, {"error": {"code": "BAD_REQUEST", "message": "Search not supported"}}
        if params.get("limit") == "1":                   # a drug missing from the full list, counted alone
            assert 'activesubstance.activesubstancename.exact:"OMEPRAZOLE"' in s and WHOLE in s
            return 200, {"meta": {"results": {"total": 10}}, "results": [{}]}
        if '"HEPATITIS"' in s:       # FAERS joins a combination's substances with a backslash
            return 200, counted({"ACETAMINOPHEN": 20, "ACETAMINOPHEN\\HYDROCODONE BITARTRATE": 15, "ASPIRIN": 15,
                                 "FAMOTIDINE\\IBUPROFEN": 12, "IBUPROFEN": 2})
        if '"NAUSEA"' in s:
            return 200, counted({"ACETAMINOPHEN": 20, "ASPIRIN": 15})
        if '"RASH"' in s:
            return 200, counted({"LOSARTAN\\HYDROCHLOROTHIAZIDE": 8, "OMEPRAZOLE": 5})
        assert "reactionmeddrapt" not in s                # the drugs of all its 1,000 reports: a full list of 100
        return 200, counted({"ACETAMINOPHEN": 1000, "ASPIRIN": 600, "FAMOTIDINE\\IBUPROFEN": 24,
                             **{f"FILLDRUG {i:03}": 50 for i in range(97)}})

    api = api_for(get)
    own = faers.searched_names("Paracetamol", "Acetaminophen")
    names = faers.name_search("Paracetamol", "Acetaminophen")
    usual = faers.UsualDrugs(api, names, WHOLE)

    def co(reaction):
        return faers.co_drug(api, names, own, reaction, WHOLE, 20, 1000, usual)

    # aspirin is in 15 of the 20 reports, but in 600 of the 1,000; the combination in 12 of 20 and 24 of 1,000
    assert co("HEPATITIS") == ("FAMOTIDINE + IBUPROFEN", 12, 24)
    assert co("NAUSEA") == (None, None, None)                   # only aspirin: a usual companion explains nothing
    # missing from the full list: the combination cannot be searched exactly, omeprazole is counted alone
    assert co("RASH") == ("OMEPRAZOLE", 5, 10)
    assert co("WERNICKE^S ENCEPHALOPATHY") == (None, None, None)     # a refused lookup loses nothing else
    assert len([p for p in asked if p.get("count") == faers.DRUG and "reactionmeddrapt" not in p["search"]]) == 1
    assert len([p for p in asked if p.get("limit") == "1"]) == 1
    assert faers.DRUG == "patient.drug.activesubstance.activesubstancename.exact"     # coded for every product
    assert faers.reaction_search("WERNICKE^S ENCEPHALOPATHY") == (
        'patient.reaction.reactionmeddrapt:"WERNICKE S ENCEPHALOPATHY"')
    assert faers.reaction_search("HEPATITIS") == 'patient.reaction.reactionmeddrapt.exact:"HEPATITIS"'


def test_a_flag_standing_on_one_repeated_case_series_is_marked():
    fake = FakeFda()
    api = api_for(fake)
    got = faers.count_ingredient(api, faers.Background(api, today=date(2026, 11, 6)), "Codamine")
    by = {r["reaction"]: r for r in got["reactions"]}
    # all 3 of the rare thing's reports: a woman aged 60 to 62 (the 9 babies aged 1 are no patient group); without
    # them nothing is left to stand out
    assert by["RARE THING"]["flagged"]
    assert (by["RARE THING"]["series_reports"], by["RARE THING"]["series_age"], by["RARE THING"]["series_sex"]) == (
        3, 61, "2")
    for name in ("HEPATITIS", "NAUSEA"):                      # not flagged: never looked at
        assert by[name]["series_reports"] is None and by[name]["series_age"] is None
    assert not [p for p in fake.asked if p.get("count") in (faers.AGE, faers.SEX) and '"RARE THING"' not in p["search"]]


def test_the_largest_group_that_could_be_one_patient():
    answers: dict[str, dict] = {}

    def get(params):
        s, count = params["search"], params.get("count")
        if "REFUSED" in s:
            return 400, {"error": {"code": "BAD_REQUEST", "message": "Search not supported"}}
        if count == faers.AGE:
            return 200, counted(answers["ages"])
        assert count == faers.SEX and f"{faers.AGE_UNIT}:801" in s
        answers["band"] = s.split(f"{faers.AGE}:")[1]
        return 200, counted(answers["sexes"])

    api = api_for(get)
    answers.update(ages={"43": 85, "44": 101, "45": 3, "70": 60, "0": 400, "41.5": 9},
                   sexes={"0": 200, "2": 180, "1": 9})
    assert faers.case_series(api, "X", 405) == (44, "2", 180)              # 43 to 45: 189 reports, 180 women
    assert answers["band"] == "[43 TO 45]"
    answers.update(ages={"55": 21, "54": 2, "72": 13})
    assert faers.case_series(api, "X", 189) is None                         # 23 of 189: under a quarter
    answers.update(ages={"55": 60, "56": 10}, sexes={"1": 30, "2": 40})
    assert faers.case_series(api, "X", 189) is None                         # 70 of 189, but no sex holds a quarter
    answers.update(ages={"1": 50, "0": 70})
    assert faers.case_series(api, "X", 120) is None                         # babies share an age
    assert faers.case_series(api, "REFUSED", 120) is None


def test_no_report_is_a_zero_not_a_failure():
    api = api_for(FakeFda())
    bg = faers.Background(api, today=date(2026, 11, 6))
    got = faers.count_ingredient(api, bg, "Nothingine")
    assert got["reports"] == 0 and got["reactions"] == [] and got["counts"] == []
    assert len(got["quarters"]) == 8


def test_a_bad_moment_is_asked_again_and_an_error_carries_openfdas_words():
    answers = iter([(429, None), (500, None), (0, None), (200, {"results": []})])
    sleeps: list[float] = []
    api = api_for(lambda p: next(answers), key="k", sleeps=sleeps)
    assert api.ask(search="x") == {"results": []}
    assert sleeps == list(faers.WAITS) and api.requests == 4

    answers = iter([(503, None)] * 4)
    with pytest.raises(OpenFdaError) as err:
        api_for(lambda p: next(answers)).ask(search="x")
    assert err.value.status == 503

    fake = FakeFda()
    with pytest.raises(OpenFdaError) as err:
        api_for(fake).ask(search="BROKENINE")
    assert "BAD_REQUEST Syntax error" in str(err.value) and len(fake.asked) == 1     # a 400 is not asked again


def test_the_key_is_sent_and_lifts_the_count_limit():
    seen: list[dict] = []

    def get(params):
        seen.append(params)
        return 404, {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}

    keyed = api_for(get, key="secret")
    assert keyed.reactions("x") == ({}, True) and keyed.total("x") == 0 and keyed.days("x") == {}
    assert seen[0] == {"search": "x", "count": faers.REACTION, "limit": "1000", "api_key": "secret"}
    assert keyed.gap == 0.25 and api_for(get).gap == 1.5



def test_a_refused_key_is_dropped_and_the_count_goes_on_without_it(caplog):
    seen: list[dict] = []

    def get(params):
        seen.append(dict(params))
        if "api_key" in params:
            return 403, {"error": {"code": "API_KEY_INVALID", "message": "An invalid api_key was supplied."}}
        return 200, {"results": [{"term": "NAUSEA", "count": 3}]}

    api = api_for(get, key="wrong")
    with caplog.at_level("WARNING"):
        assert api.reactions("x") == ({"NAUSEA": 3}, True)
    assert seen[1] == {"search": "x", "count": faers.REACTION, "limit": "100"}      # no key, the keyless limit
    assert api.key is None and api.gap == 1.5 and api.limit == 100
    assert "API_KEY_INVALID" in caplog.text and "wrong" not in caplog.text
    api.total("y")
    assert "api_key" not in seen[-1] and len(seen) == 3                               # never sent again

def test_requests_are_paced():
    sleeps: list[float] = []
    clock = iter([0.0, 0.0, 0.5, 0.5])
    api = OpenFda(lambda p: (200, {}), None, sleep=sleeps.append, clock=lambda: next(clock))
    api.ask(search="a")
    api.ask(search="b")
    assert sleeps == [1.5]                       # 40 a minute without a key


# ───────────────────────────── the run ─────────────────────────────
class FakeDb:
    def __init__(self, rows):
        self.rows, self.done, self.asked = rows, [], []

    def fetchall(self, sql, params=None):
        self.asked.append(params)
        return self.rows if "from ingredient i" in sql else []

    def fetchone(self, sql, params=None):
        return {"n": 2}

    def execute(self, sql, params=None):
        self.done.append((" ".join(sql.split())[:40], params))

    @contextmanager
    def transaction(self):
        yield self


INGREDIENTS = [{"id": "00000000-0000-0000-0000-0000000000a1", "inn_en": "Codamine"},
               {"id": "00000000-0000-0000-0000-0000000000a2", "inn_en": "Brokenine"}]


def test_a_run_stores_each_ingredient_and_never_names_one_in_the_log(caplog):
    db = FakeDb(INGREDIENTS)
    api = api_for(FakeFda())
    with caplog.at_level(logging.INFO):
        words = faers.count_reports(db, api, today=date(2026, 11, 6))
    assert words == ("1 ingredients counted (0 with no report) for Oct 2024 to Sep 2026, 2 counted in the last 6 days, "
                     f"1 to try again; {api.requests} requests to openFDA")
    stored = {p["i"] for _, p in db.done}
    assert stored == {"00000000-0000-0000-0000-0000000000a1"}             # the failed one keeps its last counts
    first = db.done[0][1]
    assert (first["n"], first["a"], first["s"]) == (200, 80000, "CODAMINE")
    quarters = next(json.loads(p["q"]) for _, p in db.done if "q" in p)
    assert len(quarters) == 8
    assert "an ingredient failed (HTTP 400)" in caplog.text
    assert "rokenine" not in caplog.text.lower() and "codamine" not in words.lower()
    assert db.asked[0] == {"force": False, "fresh": 6, "one": None}


def test_an_ingredient_is_counted_under_its_us_name_too():
    # Codaminol is the INN; FDA files it as CODAMINE, RxNorm's name for its rxcui. Without the US name: 0 reports.
    fda = FakeFda()

    def get(params):
        s = params.get("search", "")
        if "generic_name" in s and "CODAMINE" not in s:
            return 404, {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}
        return fda(params)

    asked: list[str] = []

    def us_name(rxcui: str) -> str | None:
        asked.append(rxcui)
        return {"161": "codamine", "200": "Samename"}.get(rxcui)

    db = FakeDb([{"id": "00000000-0000-0000-0000-0000000000a3", "inn_en": "Codaminol", "rxcui": "161"},
                 {"id": "00000000-0000-0000-0000-0000000000a4", "inn_en": "Samename", "rxcui": "200"},
                 {"id": "00000000-0000-0000-0000-0000000000a5", "inn_en": "Uncodedine", "rxcui": None}])
    api = api_for(get)
    words = faers.count_reports(db, api, today=date(2026, 11, 6), us_name=us_name)
    assert words.startswith("3 ingredients counted (2 with no report)")
    rows = {p["i"][-2:]: p for _, p in db.done if "s" in p}
    assert (rows["a3"]["s"], rows["a3"]["n"]) == ("CODAMINOL, CODAMINE", 200)
    assert rows["a4"]["s"] == "SAMENAME" and rows["a5"]["s"] == "UNCODEDINE"
    assert asked == ["161", "200"]                                    # no rxcui, no question to RxNorm
    assert "i.rxcui" in faers.WAITING_SQL


def test_rxnorm_not_answering_leaves_the_ingredient_for_the_next_run(caplog):
    # counting the INN alone would replace a good count with a wrong 0: the ingredient keeps its last counts
    def us_name(rxcui: str) -> str | None:
        raise ConnectionError("RxNav down")

    db = FakeDb([{"id": "00000000-0000-0000-0000-0000000000a3", "inn_en": "Codamine", "rxcui": "161"}])
    with caplog.at_level(logging.WARNING):
        words = faers.count_reports(db, api_for(FakeFda()), today=date(2026, 11, 6), us_name=us_name)
    assert "0 ingredients counted" in words and "1 to try again" in words and db.done == []
    assert "an ingredient failed (ConnectionError)" in caplog.text and "codamine" not in caplog.text.lower()


def test_nothing_waiting_asks_openfda_nothing():
    words = faers.count_reports(FakeDb([]), api_for(lambda p: 1 / 0))
    assert words == "no ingredient waits for its FAERS counts, 2 counted in the last 6 days"


def test_the_time_budget_leaves_the_rest_for_the_next_run():
    t = iter(range(1000))
    words = faers.count_reports(FakeDb(INGREDIENTS), api_for(FakeFda()), minutes=0, today=date(2026, 11, 6),
                                clock=lambda: next(t))
    assert words.startswith("0 ingredients counted") and "2 left for the next run" in words
