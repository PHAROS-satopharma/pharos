"""PHAROS — the weekly matching audit (collectors/match_audit.py), 6 Nov 2026."""

from __future__ import annotations

from collectors import match_audit
from collectors.matching import Term
from tests.test_rematch import LEVO, add_doc, issue_of, world


def watch_levofloxacin(s) -> None:
    s.ingredient[LEVO] = {"inn_en": "levofloxacin", "atc_code": "J01MA12", "active": True}
    s.terms += [Term(id="t-levo-en", term="levofloxacin", lang="en", ingredient_id=LEVO),
                Term(id="t-levo-br", term="Tavanic", lang="en", ingredient_id=LEVO, kind="brand"),
                Term(id="t-levo-syn", term="Levoflox", lang="en", ingredient_id=LEVO, kind="synonym")]


def test_a_notice_that_names_an_ingredient_but_is_not_linked_is_linked_as_history():
    s, a = world()
    watch_levofloxacin(s)
    old = add_doc(s, a, "ema-dhpc", "Quinsair: tendon rupture", days_ago=2200,
                  kept="Quinsair (levofloxacin) nebuliser solution: risk of tendon rupture.")
    brand = add_doc(s, a, "mpa-news", "Tavanic: new warning", days_ago=900, kept="Nothing else.")
    syn = add_doc(s, a, "ema-dhpc", "Levoflox tablets", days_ago=30, kept="A synonym is not one of its own words.")
    other = add_doc(s, a, "ema-dhpc", "Paracetamol: dosing", kept="Nothing about it.")
    paper = add_doc(s, a, "pubmed", "Levofloxacin tendinopathy: a cohort", kept="levofloxacin")

    out = {r["ingredient_id"]: r for r in match_audit.run(s, fields=lambda _p: [])}

    r = out[LEVO]
    assert (r["notices_named"], r["unlinked_found"], r["linked_now"], r["left_over"]) == (2, 2, 2, [])
    for did in (old, brand):
        iss = issue_of(s, did)
        assert iss and iss["is_backfill"] and (iss["id"], LEVO) in s.issue_ingredient
    for did in (syn, other, paper):
        assert issue_of(s, did) is None
    assert s.notification == []                       # history: no message
    assert s.match_audit == list(out.values())

    # the next week finds them linked, and nothing new to do
    again = {r["ingredient_id"]: r for r in match_audit.run(s, fields=lambda _p: [])}[LEVO]
    assert (again["notices_named"], again["unlinked_found"], again["linked_now"]) == (2, 0, 0)


def test_a_notice_already_matched_by_the_word_is_left_as_someone_left_it():
    s, a = world()
    watch_levofloxacin(s)
    did = add_doc(s, a, "ema-dhpc", "Levofloxacin: an old letter", kept="levofloxacin")
    s.insert_match({"document_id": did, "ingredient_id": LEVO, "term_id": "t-levo-en", "field": "title"})
    r = next(x for x in match_audit.run(s, fields=lambda _p: []) if x["ingredient_id"] == LEVO)
    assert (r["notices_named"], r["unlinked_found"]) == (1, 0) and issue_of(s, did) is None


class FakeRxNav:
    def __init__(self, names: dict[str, list[str]], ins: dict[str, list[dict]], broken: set[str] = frozenset()):
        self.names, self.ins, self.broken = names, ins, broken

    def by_name(self, name: str) -> list[str]:
        if name in self.broken:
            raise OSError("RxNav did not answer")
        return self.names.get(name, [])

    def ingredients(self, rxcui: str) -> list[dict]:
        return self.ins.get(rxcui, [])


def test_a_name_rxnorm_gives_only_to_another_substance_is_flagged():
    s, _ = world()
    watch_levofloxacin(s)
    s.audit_name_rows = [
        {"id": "n1", "ingredient_id": LEVO, "term": "Ofloxacin", "kind": "synonym", "source": "wikidata", "rxcui": "82122"},
        {"id": "n2", "ingredient_id": LEVO, "term": "Levaquin", "kind": "brand", "source": "wikidata", "rxcui": "82122"},
        {"id": "n3", "ingredient_id": LEVO, "term": "Floxacin", "kind": "synonym", "source": "wikidata", "rxcui": "82122"},
        {"id": "n4", "ingredient_id": LEVO, "term": "Levoxa", "kind": "brand", "source": "pubchem", "rxcui": "82122"},
    ]
    rx = FakeRxNav({"Ofloxacin": ["7623"], "Levaquin": ["217992"]},
                   {"7623": [{"rxcui": "7623", "name": "ofloxacin", "tty": "IN"}],
                    "217992": [{"rxcui": "82122", "name": "levofloxacin", "tty": "IN"}]},
                   broken={"Levoxa"})
    r = next(x for x in match_audit.run(s, rx, fields=lambda _p: []) if x["ingredient_id"] == LEVO)
    assert r["flagged_names"] == [{"term_id": "n1", "term": "Ofloxacin", "why": "RxNorm: ofloxacin"}]
    assert r["unchecked_names"] == 1                  # never silently passed
    assert any(t.id == "t-levo-en" for t in s.terms)  # nothing is removed by the audit


def test_names_are_checked_against_the_ingredient_of_a_stored_form_code():
    # levofloxacin was stored as 1546009, "levofloxacin anhydrous"; its names resolve to the ingredient 82122
    s, _ = world()
    watch_levofloxacin(s)
    s.audit_name_rows = [
        {"id": "n1", "ingredient_id": LEVO, "term": "Ofloxacin", "kind": "synonym", "source": "wikidata", "rxcui": "1546009"},
        {"id": "n2", "ingredient_id": LEVO, "term": "Levaquin", "kind": "brand", "source": "wikidata", "rxcui": "1546009"},
        {"id": "n3", "ingredient_id": LEVO, "term": "Levofloxacinum", "kind": "synonym", "source": "wikidata", "rxcui": "1546009"},
    ]
    rx = FakeRxNav({"Ofloxacin": ["7623"], "Levaquin": ["217992"], "Levofloxacinum": ["82122"]},
                   {"7623": [{"rxcui": "7623", "name": "ofloxacin", "tty": "IN"}],
                    "217992": [{"rxcui": "82122", "name": "levofloxacin", "tty": "IN"}],
                    "82122": [{"rxcui": "82122", "name": "levofloxacin", "tty": "IN"}],
                    "1546009": [{"rxcui": "82122", "name": "levofloxacin", "tty": "IN"}]})
    r = next(x for x in match_audit.run(s, rx, fields=lambda _p: []) if x["ingredient_id"] == LEVO)
    assert r["flagged_names"] == [{"term_id": "n1", "term": "Ofloxacin", "why": "RxNorm: ofloxacin"}]
    assert r["unchecked_names"] == 0
