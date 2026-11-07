"""A possible case report must name its ingredient in its title or abstract (collectors/case_names.py)."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, urlsplit

import httpx

from collectors import case_names
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.matching import Term
from collectors.parsers._literature import found_also

TODAY = date(2026, 11, 8)


class Web:
    """PubMed answers the PMIDs in ``named`` whose question names one of their words; Europe PMC the same by id."""

    def __init__(self, named: dict[str, set[str]], down: bool = False) -> None:
        self.named = named          # id → the words its title or abstract has
        self.down = down
        self.asked: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        q = parse_qs(urlsplit(str(req.url)).query)
        if self.down:
            return httpx.Response(503, text="down")
        if "eutils" in req.url.host:
            term = q["term"][0]
            self.asked.append(term)
            ids = re.findall(r"(\d+)\[uid\]", term)
            words = {w.lower() for w in re.findall(r'"([^"]+)"\[tiab\]', term)}
            hit = [i for i in ids if self.named.get(i, set()) & words]
            return httpx.Response(200, json={"esearchresult": {"idlist": hit}})
        query = q["query"][0]
        self.asked.append(query)
        words = {w.lower() for w in re.findall(r'TITLE_ABS:"([^"]+)"', query)}
        rows = []
        for pmcid in re.findall(r"PMCID:(PMC\d+)", query):
            if self.named.get(pmcid, set()) & words:
                rows.append({"id": pmcid, "source": "PMC", "pmcid": pmcid})
        for src, ext in re.findall(r'SRC:([A-Z]+) AND EXT_ID:"([^"]+)"', query):
            if self.named.get(ext, set()) & words:
                rows.append({"id": ext, "source": src})
        return httpx.Response(200, json={"resultList": {"result": rows}, "nextCursorMark": "*"})


def ctx_for(tmp_path, web: Web) -> FetchContext:
    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"), transport=httpx.MockTransport(web),
                       host_gap_s=0)
    ctx._sleep = lambda s: None
    return ctx


def store_with(*papers: dict) -> tuple[MemoryStore, list[str]]:
    s = MemoryStore()
    s.source["pubmed"] = {"id": "pubmed", "kind": "literature"}
    s.ingredient["ing-para"] = {"inn_en": "paracetamol", "active": True}
    s.terms += [Term(id="a", term="paracetamol", lang="en", ingredient_id="ing-para", kind="inn"),
                Term(id="b", term="acetaminophen", lang="en", ingredient_id="ing-para", kind="synonym")]
    ids = []
    for n, p in enumerate(papers):
        ids.append(s.insert_document({"source_id": "pubmed", "external_id": f"x{n}", "title_orig": "A case report",
                                      "doc_type": "literature", "structured": p}))
    return s, ids


def paper(pmid=None, *, kinds=("name",), pmcid=None, epmc=None, case=True) -> dict:
    queries = [{"query": "paracetamol" if k == "name" else "anilides", "kind": k, "db": ["pubmed"]} for k in kinds]
    return {"pmid": pmid, "pmcid": pmcid, "queries": queries,
            "europepmc_url": f"https://europepmc.org/article/{epmc[0]}/{epmc[1]}" if epmc else None,
            "case_report": {"reason": "pubtype"} if case else None}


def test_a_flagged_paper_keeps_its_flag_only_when_its_title_or_abstract_names_the_ingredient(tmp_path):
    store, (named, other, synonym) = store_with(paper("1"), paper("2"), paper("3"))
    web = Web({"1": {"paracetamol"}, "3": {"acetaminophen"}})
    got = case_names.check(ctx_for(tmp_path, web), store, TODAY)
    assert got == {"kept": 2, "cleared": 1, "waiting": 0}
    assert store.document[named]["structured"]["case_report"] == {"reason": "pubtype"}
    assert store.document[synonym]["structured"]["case_report"] == {"reason": "pubtype"}    # its other name counts
    cleared = store.document[other]["structured"]
    assert cleared["case_report"] is None and cleared["case_report_was"] == {"reason": "pubtype"}
    assert {store.document[i]["structured"]["names_checked"] for i in (named, other, synonym)} == {"2026-11-08"}
    # one question for the three, in titles and abstracts, with every English name
    assert len(web.asked) == 1 and '"paracetamol"[tiab] OR "acetaminophen"[tiab]' in web.asked[0]
    # each paper is asked once
    assert case_names.check(ctx_for(tmp_path, web), store, TODAY) == {"kept": 0, "cleared": 0, "waiting": 0}


def test_a_paper_only_class_words_found_is_cleared_without_asking(tmp_path):
    store, (cls,) = store_with(paper("9", kinds=("class",)))
    web = Web({"9": {"paracetamol"}})
    assert case_names.check(ctx_for(tmp_path, web), store, TODAY)["cleared"] == 1
    assert store.document[cls]["structured"]["case_report"] is None and web.asked == []


def test_a_paper_with_no_pmid_is_asked_of_europe_pmc(tmp_path):
    store, (pmc, ppr, gone) = store_with(paper(pmcid="PMC5"), paper(epmc=("PPR", "PPR7")), paper(pmcid="PMC6"))
    web = Web({"PMC5": {"paracetamol"}, "PPR7": {"acetaminophen"}})
    assert case_names.check(ctx_for(tmp_path, web), store, TODAY) == {"kept": 2, "cleared": 1, "waiting": 0}
    assert store.document[gone]["structured"]["case_report"] is None
    assert "TITLE_ABS:" in web.asked[0] and "PMCID:PMC5" in web.asked[0]


def test_a_paper_whose_question_was_not_answered_waits_for_the_next_run(tmp_path):
    store, (p,) = store_with(paper("1"))
    assert case_names.check(ctx_for(tmp_path, Web({}, down=True)), store, TODAY) == {
        "kept": 0, "cleared": 0, "waiting": 1}
    s = store.document[p]["structured"]
    assert s["case_report"] == {"reason": "pubtype"} and "names_checked" not in s


def test_a_paper_not_flagged_is_never_asked(tmp_path):
    store, _ = store_with(paper("1", case=False))
    web = Web({})
    assert case_names.check(ctx_for(tmp_path, web), store, TODAY) == {"kept": 0, "cleared": 0, "waiting": 0}
    assert web.asked == []


def test_a_cleared_flag_comes_back_to_be_checked_when_a_name_search_finds_the_paper():
    s = {**paper("9", kinds=("class",), case=False), "case_report_was": {"reason": "title"}, "names_checked": "x"}
    again = found_also(s, "europepmc", {"paracetamol": "name"})
    assert again["case_report"] == {"reason": "title"} and "names_checked" not in again
    # a class word finding it again changes nothing
    assert found_also(s, "europepmc", {"anilides": "class"})["case_report"] is None
