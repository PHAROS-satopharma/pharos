"""PHAROS — France (spc-bdpm): a substance written with an accent is still found.

On 6 Nov 2026 the label watch found no French carvedilol product although the BDPM lists Kredex and
its generics: the bulk file writes the substance "CARVÉDILOL" (Latin-1 byte 0xC9 for É), and the
term "carvedilol" is not a substring of it. The rows below are real rows of CIS_COMPO_bdpm.txt and
CIS_bdpm.txt, downloaded 6 Nov 2026 (ISO-8859-1, CRLF, served as application/octet-stream).
"""

from __future__ import annotations

import pytest

from collectors.spc import bdpm
from tests.fakes_a2 import FakeCtx

COMPO = [
    "61271735\tcomprimé\t27222\tCARVÉDILOL\t12,50 mg\tun comprimé\tSA\t1",
    "68296050\tcomprimé\t27222\tCARVÉDILOL\t25 mg\tun comprimé\tSA\t1",
]
CIS = [
    "61271735\tKREDEX 12,5 mg, comprimé sécable\tcomprimé sécable\torale\tAutorisation active\t"
    "Procédure nationale\tCommercialisée\t27/12/1996\t\t\t CHEPLAPHARM ARZNEIMITTEL (ALLEMAGNE)\tNon",
    "68296050\tKREDEX 25 mg, comprimé sécable\tcomprimé sécable\torale\tAutorisation active\t"
    "Procédure nationale\tCommercialisée\t30/08/1991\t\t\t CHEPLAPHARM ARZNEIMITTEL (ALLEMAGNE)\tNon",
]


def _latin1(lines: list[str]) -> bytes:
    return ("\r\n".join(lines) + "\r\n").encode("latin-1")


@pytest.mark.parametrize("terms", [["carvedilol"], ["carvédilol"], ["CARVEDILOL"], ["Carvédilol"]])
def test_match_cis_folds_accents_on_both_sides(terms):
    rows = [ln.split("\t") for ln in COMPO]
    assert bdpm.match_cis(rows, terms) == {"61271735", "68296050"}


def test_match_cis_accent_folding_does_not_widen_the_match():
    rows = [ln.split("\t") for ln in COMPO]
    assert bdpm.match_cis(rows, ["carbidopa"]) == set()
    assert bdpm.match_cis(rows, [""]) == set()


@pytest.mark.parametrize("terms", [["carvedilol"], ["carvédilol"]])
def test_discover_reads_latin1_bytes_and_finds_carvedilol(terms):
    ctx = FakeCtx({bdpm.COMPO_URL: _latin1(COMPO), bdpm.CIS_URL: _latin1(CIS)})
    got = bdpm.discover(ctx, {"inn_en": "carvedilol", "terms": {"fr": terms}})
    assert [p.national_id for p in got] == ["61271735", "68296050"]
    assert got[0].product_name == "KREDEX 12,5 mg, comprimé sécable"
    assert got[0].mah == "CHEPLAPHARM ARZNEIMITTEL (ALLEMAGNE)"
    assert got[0].extra == {"commercialisation": "Commercialisée", "procedure": "Procédure nationale"}


def test_discover_falls_back_to_the_english_inn_without_a_french_term():
    ctx = FakeCtx({bdpm.COMPO_URL: _latin1(COMPO), bdpm.CIS_URL: _latin1(CIS)})
    got = bdpm.discover(ctx, {"inn_en": "Carvedilol", "terms": {}})
    assert [p.national_id for p in got] == ["61271735", "68296050"]
