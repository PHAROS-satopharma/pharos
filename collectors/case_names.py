"""PHAROS — a possible case report must name its ingredient (owner, 8 Nov 2026: "stop flagging case reports that
don't name the ingredient").

A literature paper is flagged as a possible case report (``structured.case_report``, collectors/parsers/pubmed.py)
when PubMed types it Case Reports or its title says so, and the flag starts a 15-day reporting clock. Until 7 Nov
2026 the literature was searched in whole papers and by drug class, so thousands of flagged papers only mentioned
the ingredient somewhere in their full text, or did not name it at all. A flagged paper now keeps its flag only
when its title or abstract names an ingredient whose name search found it: the English INN or one of its other
English names matched as words (``Store.literature_names``). PubMed is asked ``(<pmid>[uid] OR …) AND
("name"[tiab] OR …)``; a paper with no PMID is asked of Europe PMC by its PMC or Europe PMC id with TITLE_ABS. A
paper only class words found names no ingredient, so its flag is cleared without asking.

Each flagged paper is asked once: ``structured.names_checked`` records the Cairo day of the check, and a cleared
flag is kept as ``structured.case_report_was`` (``Store.mark_case_names``). A paper whose question could not be
answered (NCBI or Europe PMC down) is left for the next run. The literature runs call ``check`` after their
searches (collectors/run.py), so the papers stored before 8 Nov are checked by the first runs and every new
flagged paper by the run that stores it. The name searches look in titles and abstracts since 7 Nov, so a paper
they found keeps its flag.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date
from typing import Any
from urllib.parse import quote

from collectors.parsers import europepmc, pubmed

log = logging.getLogger(__name__)

CHECK_LIMIT = 6_000          # flagged papers read per run (about 2,500 were waiting on 8 Nov 2026)
PMIDS_PER_ASK = 100          # PubMed ids in one question (the URL stays short)
IDS_PER_ASK = 50             # Europe PMC ids in one question
EPMC_URL = re.compile(r"/article/([A-Z]+)/([^/?#]+)")


def names_of(structured: dict) -> list[str]:
    """The ingredient names whose searches found the paper (``queries`` of kind name), each once."""
    out: dict[str, str] = {}
    for q in structured.get("queries") or []:
        if isinstance(q, dict) and q.get("kind") == "name" and str(q.get("query") or "").strip():
            word = str(q["query"]).strip()
            out.setdefault(word.casefold(), word)
    return list(out.values())


def _words(inn: str, others: dict[str, list[str]]) -> list[str]:
    got: dict[str, str] = {}
    for w in [inn, *(others.get(inn) or [])]:
        w = " ".join(str(w).replace('"', "").split())
        if w:
            got.setdefault(w.casefold(), w)
    return list(got.values())


def _epmc_key(structured: dict) -> str | None:
    """The paper as Europe PMC is asked for it: its PMC id, else its Europe PMC source and id."""
    pmcid = str(structured.get("pmcid") or "")
    if pmcid.startswith("PMC"):
        return f"PMCID:{pmcid}"
    m = EPMC_URL.search(str(structured.get("europepmc_url") or ""))
    if m:
        return f"(SRC:{m[1]} AND EXT_ID:{europepmc.phrase(m[2])})"
    return None


def _ask_pubmed(ctx: Any, pmids: list[str], words: list[str]) -> set[str]:
    pubmed._pace(ctx)
    term = (f"({' OR '.join(f'{p}[uid]' for p in pmids)}) AND ("
            + " OR ".join(f'"{w}"[tiab]' for w in words) + ")")
    url = (f"{pubmed.EUTILS}/esearch.fcgi?db=pubmed&retmode=json&retmax={len(pmids) + 10}"
           f"&term={quote(term, safe='')}{pubmed._common()}")
    data = pubmed._get_json(ctx, url)
    return {str(i) for i in (data.get("esearchresult") or {}).get("idlist") or []}


def _ask_europepmc(ctx: Any, keys: list[str], words: list[str]) -> list[dict]:
    q = (f"({' OR '.join(keys)}) AND ("
         + " OR ".join(f"TITLE_ABS:{europepmc.phrase(w)}" for w in words) + ")")
    rows: list[dict] = []
    for page in europepmc.pages(ctx, q, "idlist", len(keys) + 10):
        rows.extend(page)
    return rows


def _epmc_hit(structured: dict, rows: list[dict]) -> bool:
    pmcid = str(structured.get("pmcid") or "")
    m = EPMC_URL.search(str(structured.get("europepmc_url") or ""))
    for r in rows:
        if pmcid and str(r.get("pmcid") or "") == pmcid:
            return True
        if m and str(r.get("source") or "") == m[1] and str(r.get("id") or "") == m[2]:
            return True
    return False


def check(ctx: Any, store: Any, today: date, *, limit: int = CHECK_LIMIT,
          deadline: float | None = None) -> dict[str, int]:
    """Check the flagged papers not checked yet; returns how many kept their flag, lost it, or wait."""
    papers = store.case_reports_unchecked(limit)
    if not papers:
        return {"kept": 0, "cleared": 0, "waiting": 0}
    others = store.literature_names("en")
    named: set[str] = set()
    cleared: list[str] = []
    asked: set[str] = set()            # papers whose every question was answered
    by_pubmed: dict[str, dict[str, list[str]]] = {}     # INN → pmid → document ids
    by_epmc: dict[str, list[dict]] = {}                 # INN → papers
    pending: dict[str, int] = {}                        # document id → questions not answered yet
    for p in papers:
        s = p["structured"]
        inns = names_of(s)
        if not inns:
            cleared.append(p["id"])     # only class words found it: it names no ingredient
            continue
        for inn in inns:
            pmid = str(s.get("pmid") or "")
            if pmid.isdigit():
                by_pubmed.setdefault(inn, {}).setdefault(pmid, []).append(p["id"])
            elif _epmc_key(s):
                by_epmc.setdefault(inn, []).append(p)
            else:
                continue                # nothing to ask by: counted as not naming it
            pending[p["id"]] = pending.get(p["id"], 0) + 1

    def answered(doc_id: str) -> None:
        pending[doc_id] -= 1
        if pending[doc_id] == 0:
            asked.add(doc_id)

    def late() -> bool:
        return deadline is not None and time.monotonic() > deadline

    for inn, pmids in by_pubmed.items():
        words = _words(inn, others)
        ids = list(pmids)
        for i in range(0, len(ids), PMIDS_PER_ASK):
            if late():
                break
            chunk = ids[i:i + PMIDS_PER_ASK]
            try:
                hits = _ask_pubmed(ctx, chunk, words)
            except Exception as e:  # noqa: BLE001 - asked again on the next run
                log.warning("case report names: PubMed did not answer: %s", e)
                continue
            for pmid in chunk:
                for doc_id in pmids[pmid]:
                    if pmid in hits:
                        named.add(doc_id)
                    answered(doc_id)
    for inn, group in by_epmc.items():
        words = _words(inn, others)
        for i in range(0, len(group), IDS_PER_ASK):
            if late():
                break
            chunk = group[i:i + IDS_PER_ASK]
            try:
                rows = _ask_europepmc(ctx, [_epmc_key(p["structured"]) for p in chunk], words)
            except Exception as e:  # noqa: BLE001 - asked again on the next run
                log.warning("case report names: Europe PMC did not answer: %s", e)
                continue
            for p in chunk:
                if _epmc_hit(p["structured"], rows):
                    named.add(p["id"])
                answered(p["id"])
    no_id = [p["id"] for p in papers if names_of(p["structured"]) and p["id"] not in pending]
    keep = sorted(named & asked)
    drop = sorted(set(cleared) | set(no_id) | (asked - named))
    store.mark_case_names(keep, drop, today.isoformat())
    waiting = len(papers) - len(keep) - len(drop)
    log.info("case report names: %d keep their flag, %d do not name their ingredient, %d wait",
             len(keep), len(drop), waiting)
    return {"kept": len(keep), "cleared": len(drop), "waiting": waiting}
