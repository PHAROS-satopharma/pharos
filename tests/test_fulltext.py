"""PHAROS — legal open-access full text from Unpaywall (collectors/fulltext.py, migration 0068, validation row 22).

Unpaywall's answers are the ones it gave on 6 November 2026 for 10.1038/nature12373 (open: the publisher's PDF,
an arXiv preprint and repository copies) and 10.1002/pds.5000 (closed), recorded without the authors' names. No
network: Unpaywall and PubMed are fakes, the PDF hosts go through httpx.MockTransport and DNS through a fake
resolver."""

from __future__ import annotations

import base64
import copy
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from collectors import fulltext
from collectors.cases import paper, read
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.parsers.pubmed import clean_doi, doi_of
from tests.test_cases import FULL, CaseDb

FIX = Path(__file__).parent / "fixtures" / "unpaywall"
OPEN = json.loads((FIX / "open-10.1038_nature12373.json").read_text(encoding="utf-8"))
CLOSED = json.loads((FIX / "closed-10.1002_pds.5000.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
PDF_BYTES = b"%PDF-1.5\n" + b"0" * 2000 + b"\n%%EOF"
CASE_ID = "00000000-0000-0000-0000-0000000068c1"

DNS = {"www.nature.com": ["151.101.0.95"], "arxiv.org": ["151.101.3.42"], "api.unpaywall.org": ["104.26.0.1"],
       "eutils.ncbi.nlm.nih.gov": ["130.14.29.110"], "metadata.test": ["169.254.169.254"],
       "intranet.test": ["10.1.2.3"]}


def fake_resolve(host: str) -> list[str]:
    if host not in DNS:
        raise OSError(f"no such host {host}")
    return DNS[host]


def serve_pdfs(req: httpx.Request) -> httpx.Response:
    """nature.com sends its cookie page instead of the PDF (as it did live); arXiv sends the PDF."""
    if req.url.host == "www.nature.com":
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              text="<html><body>" + "Cookies are not supported. " * 2000 + "</body></html>")
    if req.url.host == "arxiv.org":
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF_BYTES)
    if req.url.host == "api.unpaywall.org":
        return httpx.Response(200, headers={"content-type": "application/json"}, content=json.dumps(OPEN).encode())
    return httpx.Response(404)


def pdf_ctx(handler=serve_pdfs, max_bytes: int = fulltext.MAX_PDF_BYTES) -> tuple[FetchContext, list[str]]:
    """The fetcher fulltext.pdf_context() makes, on a fake network: public hosts only, nothing archived."""
    seen: list[str] = []

    def recording(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return handler(req)

    ctx = FetchContext(None, "open-access", archive=Archive(enabled=False), transport=httpx.MockTransport(recording),
                       host_gap_s=0, public_only=True, max_bytes=max_bytes)
    ctx._sleep = lambda s: None
    ctx._resolve = fake_resolve
    return ctx, seen


class FakeDb:
    def __init__(self, rows: dict[str, list[dict]] | None = None) -> None:
        self.rows, self.done = rows or {}, []

    def fetchall(self, sql, params=None):
        for key, rows in self.rows.items():
            if key in sql:
                return rows
        return []

    def execute(self, sql, params=None):
        self.done.append((" ".join(sql.split())[:40], params))

    @contextmanager
    def transaction(self):
        yield self


# ───────────────────────────── DOIs ─────────────────────────────

def test_a_doi_comes_from_the_article_ids_else_the_elocation_id():
    assert doi_of({"articleids": [{"idtype": "pubmed", "value": "1"},
                                  {"idtype": "doi", "value": "10.2147/RRU.S650380"}]}) == "10.2147/RRU.S650380"
    assert doi_of({"articleids": [{"idtype": "pubmed", "value": "1"}],
                   "elocationid": "pii: S0140-6736(26)00001-2. doi: 10.1016/S0140-6736(26)00001-2."}) \
        == "10.1016/S0140-6736(26)00001-2"
    assert doi_of({"articleids": [], "elocationid": "pii: e12345"}) is None and doi_of(None) is None
    assert clean_doi("https://doi.org/10.1038/nature12373") == "10.1038/nature12373"
    assert clean_doi("not a doi") is None and clean_doi(None) is None


def test_papers_without_a_doi_are_asked_in_pubmed_again():
    rows = [{"id": "doc-a", "pmid": "111"}, {"id": "doc-b", "pmid": "222"}]
    db = FakeDb({"doi_checked": rows})
    answer = {"result": {"uids": ["111", "222"],
                         "111": {"uid": "111", "articleids": [], "elocationid": "doi: 10.1002/pds.5000"},
                         "222": {"uid": "222", "articleids": [], "elocationid": ""}}}
    assert fulltext.fill_dois(db, fetch=lambda pmids: answer) == "1 DOIs found, 1 papers still without one"
    assert [p["doi"] for _, p in db.done] == ["10.1002/pds.5000", None]      # both marked as asked

    db = FakeDb({"doi_checked": rows})
    assert "2 to try again" in fulltext.fill_dois(db, fetch=lambda pmids: 1 / 0) and db.done == []


# ───────────────────────────── what Unpaywall says ─────────────────────────────

def test_a_closed_paper_is_kept_as_closed():
    assert fulltext.open_access(CLOSED) == {"is_oa": False, "known": True, "oa_status": "closed"}


def test_an_open_paper_keeps_its_best_location_and_the_pdfs_to_try():
    oa = fulltext.open_access(OPEN)
    assert oa["is_oa"] and oa["known"] and oa["oa_status"] == "bronze"
    assert (oa["url"], oa["pdf_url"], oa["license"], oa["version"], oa["host_type"]) == (
        "https://www.nature.com/articles/nature12373.pdf", "https://www.nature.com/articles/nature12373.pdf",
        None, "published", "publisher")
    # the best first, then the repositories; a location without a PDF is not a PDF to try
    assert [(p["pdf_url"], p["version"], p["host_type"]) for p in oa["pdfs"]] == [
        ("https://www.nature.com/articles/nature12373.pdf", "published", "publisher"),
        ("https://arxiv.org/pdf/1304.1068", "submitted", "repository")]


def test_a_doi_unpaywall_does_not_know_and_a_link_that_is_not_http():
    ask = fulltext.make_ask(lambda url: (404, b"<html>404 Not Found</html>"))
    assert fulltext.open_access(ask("10.9999/not-a-real-doi")) == {"is_oa": False, "known": False}
    odd = copy.deepcopy(OPEN)
    odd["best_oa_location"]["url"] = odd["best_oa_location"]["url_for_pdf"] = "javascript:alert(1)"
    odd["best_oa_location"]["url_for_landing_page"] = None
    assert fulltext.open_access(odd)["is_oa"] is False      # nothing a page could link to
    with pytest.raises(RuntimeError):
        fulltext.make_ask(lambda url: (503, b""))("10.1038/nature12373")
    assert fulltext.unpaywall_url("10.1016/S0140-6736(20)30183-5") == (
        "https://api.unpaywall.org/v2/10.1016/S0140-6736(20)30183-5?email=pharos@satopharma.com")


def test_each_paper_is_asked_once_and_a_failure_never_stops_the_batch():
    rows = [{"id": "doc-open", "doi": "10.1038/nature12373"}, {"id": "doc-open-2", "doi": "10.1038/NATURE12373"},
            {"id": "doc-closed", "doi": "10.1002/pds.5000"}, {"id": "doc-broken", "doi": "10.1000/broken"},
            {"id": "doc-unknown", "doi": "10.9999/unknown"}, {"id": "doc-no-doi", "doi": "pii: S1"}]
    db = FakeDb({"from document d": rows})
    asked = []

    def ask(doi):
        asked.append(doi)
        if doi == "10.1000/broken":
            raise TimeoutError
        return {"10.1038/nature12373": OPEN, "10.1002/pds.5000": CLOSED}.get(doi)

    words = fulltext.check_papers(db, ask)
    assert asked == ["10.1038/nature12373", "10.1002/pds.5000", "10.1000/broken", "10.9999/unknown"]
    stored = {p["id"]: json.loads(p["oa"]) for _, p in db.done}
    assert set(stored) == {"doc-open", "doc-open-2", "doc-closed", "doc-unknown"}   # the failed one waits
    assert stored["doc-open"]["is_oa"] and not stored["doc-closed"]["is_oa"] and not stored["doc-unknown"]["known"]
    assert words == "1 papers with a free full text, 1 without one, 1 not known to Unpaywall, 1 to try again"


def test_a_run_stops_at_its_time_budget():
    rows = [{"id": f"doc-{i}", "doi": f"10.1000/{i}"} for i in range(5)]
    ticks = iter(range(0, 1000, 100))
    words = fulltext.check_papers(FakeDb({"from document d": rows}), lambda doi: CLOSED, budget_s=250,
                                  clock=lambda: next(ticks))
    # the clock reads 100 s more at each paper: the third is past the 250 s budget, so three wait
    assert words == "0 papers with a free full text, 2 without one, 0 not known to Unpaywall, 3 wait for the next run"


def test_nothing_waiting_asks_nothing():
    assert fulltext.check_papers(FakeDb(), lambda doi: 1 / 0) == "no paper waits for Unpaywall"


def test_a_paper_with_no_open_copy_is_asked_again_after_30_days():
    def at(days: int) -> str:
        return (NOW - timedelta(days=days)).isoformat()

    assert fulltext.due(None, NOW)                                              # never asked
    assert not fulltext.due({"is_oa": False, "checked": at(29)}, NOW)           # closed, asked 29 days ago
    assert fulltext.due({"is_oa": False, "checked": at(31)}, NOW)               # closed, 31 days ago: again
    assert fulltext.due({"is_oa": False, "known": False, "checked": at(31)}, NOW)
    assert not fulltext.due({"is_oa": True, "checked": at(400)}, NOW)           # open: never again
    assert fulltext.due({"is_oa": False, "checked": "garbage"}, NOW)
    # the daily query says the same
    assert "'is_oa', '') <> 'true'" in fulltext.PENDING_SQL and "%(recheck)s" in fulltext.PENDING_SQL


# ───────────────────────────── a case's open PDF ─────────────────────────────

def _doc(structured: dict) -> dict:
    return {"id": "doc-1", "url": "https://pubmed.ncbi.nlm.nih.gov/111/", "title_orig": "Hepatitis after casoxicam",
            "structured": {"pmid": "111", "pmcid": None, "doi": "10.1038/nature12373", **structured}}


def _licensed() -> dict:
    """The recorded answer with a licence on the arXiv copy, so the licence kept with the PDF can be seen."""
    data = copy.deepcopy(OPEN)
    for loc in data["oa_locations"]:
        if loc.get("url_for_pdf") == "https://arxiv.org/pdf/1304.1068":
            loc["license"] = "cc-by"
    return data


def test_a_case_archives_the_first_copy_that_arrives_as_a_pdf_with_its_licence(tmp_path):
    archive = Archive(tmp_path)
    ctx, seen = pdf_ctx()
    got = paper.open_pdf(_doc({"oa": fulltext.open_access(_licensed())}), archive, "CASE-2026-068", ctx)
    # the publisher's cookie page is not a PDF: the arXiv copy is taken
    assert seen == ["https://www.nature.com/articles/nature12373.pdf", "https://arxiv.org/pdf/1304.1068"]
    assert got["pdf_url"] == "https://arxiv.org/pdf/1304.1068" and got["bytes"] == len(PDF_BYTES)
    assert archive.get(got["key"]) == PDF_BYTES
    assert archive.meta(got["key"]) == {
        "licence": "cc-by", "version": "submitted", "host-type": "repository",
        "source-url": "https://arxiv.org/pdf/1304.1068", "doi": "10.1038/nature12373", "found-by": "Unpaywall"}
    text = paper.build_text(_doc({}), "Abstract.", "", got)
    assert f"Open-access PDF: {got['key']}" in text
    assert "licence cc-by, submitted version, from a repository (https://arxiv.org/pdf/1304.1068)" in text


def test_an_unsafe_host_is_refused_before_any_request(tmp_path):
    oa = fulltext.open_access(_licensed())
    oa["pdfs"] = [{"pdf_url": "http://metadata.test/latest/paper.pdf", "license": None, "version": "published",
                   "host_type": "repository"},
                  {"pdf_url": "http://intranet.test/paper.pdf", "license": None, "version": "published",
                   "host_type": "repository"}, *oa["pdfs"]]
    ctx, seen = pdf_ctx()
    pdf, loc, tried = fulltext.fetch_open_pdf(ctx, oa)
    assert not any("metadata.test" in u or "intranet.test" in u for u in seen)      # never requested
    assert tried[:2] == ["metadata.test: not a public address, refused", "intranet.test: not a public address, refused"]
    assert pdf == PDF_BYTES and loc["pdf_url"] == "https://arxiv.org/pdf/1304.1068"


def test_a_redirect_inside_is_refused_too():
    def redirect(req):
        if req.url.host == "arxiv.org":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
        return serve_pdfs(req)

    ctx, seen = pdf_ctx(redirect)
    pdf, loc, tried = fulltext.fetch_open_pdf(ctx, fulltext.open_access(OPEN))
    assert pdf is None and loc is None and "169.254.169.254" not in " ".join(seen)
    assert tried == ["www.nature.com: not a PDF (text/html)", "arxiv.org: not a public address, refused"]


def test_a_pdf_over_the_size_limit_is_refused():
    ctx, _ = pdf_ctx(max_bytes=1000)
    pdf, _, tried = fulltext.fetch_open_pdf(ctx, fulltext.open_access(OPEN))
    assert pdf is None and tried[-1] == "arxiv.org: FetchError"
    assert not fulltext.is_pdf("application/pdf", b"<html>") and not fulltext.is_pdf("text/html", PDF_BYTES)


def test_the_open_copy_fetcher_reads_public_hosts_only_and_archives_nothing_unchecked():
    ctx = fulltext.pdf_context()
    try:
        assert ctx.public_only and ctx.max_bytes == fulltext.MAX_PDF_BYTES and ctx.archiver.backend == "disabled"
    finally:
        ctx.close()


def test_a_case_paper_without_a_doi_or_an_open_copy_asks_for_no_pdf(tmp_path):
    archive = Archive(tmp_path)
    ctx, seen = pdf_ctx()
    assert paper.open_pdf(_doc({"doi": None}), archive, "CASE-2026-068", ctx) is None
    closed = {"oa": {**fulltext.open_access(CLOSED), "checked": datetime.now(timezone.utc).isoformat()}}
    assert paper.open_pdf(_doc(closed), archive, "CASE-2026-068", ctx) is None
    assert seen == []                                    # neither Unpaywall nor a host was asked
    text = paper.build_text(_doc({}), "Abstract.", "", None)
    assert "Open-access PDF:" not in text and "only the record above was read" in text


def test_a_case_paper_not_asked_yet_is_asked_now(tmp_path):
    ctx, seen = pdf_ctx()
    got = paper.open_pdf(_doc({}), Archive(tmp_path), "CASE-2026-068", ctx)
    assert seen[0].startswith("https://api.unpaywall.org/v2/10.1038/nature12373?email=")
    assert got["key"].startswith("sha256/")


def test_an_open_copy_that_cannot_be_fetched_is_said_and_the_record_is_read(tmp_path):
    ctx, _ = pdf_ctx(lambda req: httpx.Response(403, headers={"content-type": "text/plain"}, text="Forbidden"))
    got = paper.open_pdf(_doc({"oa": fulltext.open_access(OPEN)}), Archive(tmp_path), "CASE-2026-068", ctx)
    assert "key" not in got and len(got["tried"]) == 2
    text = paper.build_text(_doc({}), "Abstract.", "", got)
    assert "Open-access PDF:" not in text and "could not fetch it as a PDF" in text


class PaperDb(CaseDb):
    """A case opened from a paper: the paper's row, and the case's original set on it."""

    def __init__(self, case: dict, doc: dict):
        super().__init__(case)
        self.doc = doc

    def fetchone(self, sql, params=None):
        if sql.startswith("select id, url, title_orig, structured from document"):
            return self.doc
        if sql.lstrip().startswith("update safety_case set r2_key"):
            self.case.update(r2_key=params["k"], sha256=params["s"], mime="text/plain", bytes=params["b"])
            return dict(self.case)
        return super().fetchone(sql, params)


def test_the_reader_receives_the_record_and_the_open_pdf(tmp_path):
    archive = Archive(tmp_path)
    case = {"id": CASE_ID, "ref": "CASE-2026-068", "origin": "paper", "status": "queued", "read_attempts": 0,
            "document_id": "doc-1", "r2_key": None, "sha256": None, "mime": None, "file_name": None,
            "ingredient_id": None}
    db = PaperDb(case, _doc({"oa": fulltext.open_access(_licensed())}))

    def ncbi(req):
        assert req.url.host == "eutils.ncbi.nlm.nih.gov" and req.url.params["db"] == "pubmed"
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="1. Hepatitis after casoxicam.")

    ncbi_ctx = FetchContext(None, "cases", archive=archive, transport=httpx.MockTransport(ncbi), host_gap_s=0,
                            public_only=True)
    ncbi_ctx._sleep, ncbi_ctx._resolve = (lambda s: None), fake_resolve
    open_ctx, _ = pdf_ctx()
    given = {}

    def reader(blocks, ingredients):
        given["blocks"] = blocks
        return {"is_case": True, "serious": "yes", **json.loads(json.dumps(FULL, default=str)),
                "evidence": []}, "claude-opus-5-5"

    status = read.read_case(db, archive, read.claim(db), reader=reader,
                            fetch_paper=lambda d, a, c: paper.fetch_source(d, a, c, ncbi_ctx, open_ctx))
    assert status == "to_confirm"
    text, pdf = given["blocks"]
    assert text["source"]["media_type"] == "text/plain" and "Open-access PDF: sha256/" in text["source"]["data"]
    assert pdf["source"] == {"type": "base64", "media_type": "application/pdf",
                             "data": base64.standard_b64encode(PDF_BYTES).decode()}


def test_a_tampered_open_pdf_is_never_read(tmp_path):
    archive = Archive(tmp_path)
    sha, key = archive.put(PDF_BYTES, "application/pdf")
    text = f"Title: x\nOpen-access PDF: {key}\n\nPubMed record:\n(no abstract)".encode()
    assert paper.attached_pdf_blocks(text, archive)[0]["source"]["media_type"] == "application/pdf"
    (tmp_path / key).write_bytes(PDF_BYTES + b"changed")
    with pytest.raises(read.ReadFailed, match="does not match its SHA-256"):
        paper.attached_pdf_blocks(text, archive)
    assert paper.attached_pdf_blocks(b"Title: x\n\nPubMed record:\n(no abstract)", archive) == []
