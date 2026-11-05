"""PHAROS — the MFDS safety letter PDFs are printed in two columns and are read column by column.

``tests/fixtures/mfds-letters/sample.pdf`` is a real 의약품 정보 서한 (설글리코타이드, 5 Feb 2026, Hancom
PDF). Read straight across (``pdftotext -layout``), the right column's "조치대상 의약품" heading came
before the left column's "주요내용", and a left line ran into the right one beside it. Needs poppler's
``pdftotext`` (``-bbox``); on the CI runner: poppler-utils.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
from datetime import date

import httpx
import pytest

from collectors.alerts import Notifier
from collectors.core.archive import Archive
from collectors.core.context import FetchContext
from collectors.core.memstore import MemoryStore
from collectors.core.models import Item
from collectors.core.registry import load_catalogue, sync_catalogue
from collectors.parsers import mfds
from collectors.run import Runner, SourceStats
from tests.fakes_a2 import fixture

PDF_URL = mfds.DOWNLOAD + "1PmiENXsZC6"


def _poppler() -> bool:
    exe = shutil.which("pdftotext")
    if not exe:
        return False
    proc = subprocess.run([exe, "-v"], capture_output=True, check=False)
    return b"poppler" in (proc.stdout + proc.stderr).lower()


needs_poppler = pytest.mark.skipif(not _poppler(), reason="needs poppler's pdftotext (-bbox)")


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    for var in ("TELEGRAM_BOT_TOKEN", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DRY_RUN", "1")


def _stored_attachment_text(tmp_path) -> str:
    _, sources, _ = load_catalogue()
    src = dataclasses.replace(next(s for s in sources if s.id == "mfds-letters"), options={"detail": "never"})
    content = fixture("mfds-letters/sample.pdf")

    def serve(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PDF_URL, request.url
        return httpx.Response(200, content=content, headers={"content-type": "application/pdf"})

    store = MemoryStore()
    store.load_seed()
    sync_catalogue(store)
    ctx = FetchContext(None, store.create_run("manual", "test-sha"), archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(serve), host_gap_s=0)
    item = Item(external_id="mfds:516", url="https://nedrug.mfds.go.kr/pbp/CCBAC01/getItem?safeLetterNo=516",
                title="안전성 서한 배포 알림", published=date(2026, 2, 5), doc_type="dhpc", lang="ko",
                attachment_urls=[PDF_URL])
    runner = Runner(store, ctx, Notifier(store, store.settings()), store.settings())
    read: list[list[dict]] = []
    real = runner._attachments

    def attachments(*a, **k):  # the text is stored only for a letter that matched: keep what was read
        read.append(real(*a, **k))
        return read[-1]

    runner._attachments = attachments
    try:
        runner.process_item(src, mfds, item, seed=True, stats=SourceStats())
    finally:
        ctx.close()
    ((att,),) = read
    assert att["extraction"] == "text" and att["words"] > 500
    assert list(store.attachment.values())[0]["words"] == att["words"]
    return att["text"]


@needs_poppler
def test_the_letter_is_read_left_column_first(tmp_path):
    text = _stored_attachment_text(tmp_path)
    # left column: 정보사항 → 주요내용 → its last line; only then the right column's headings
    assert text.index("정보사항") < text.index("주요내용") < text.index("조치대상 의약품")
    assert text.index("주요내용") < text.index("의약전문가를 위한 권고사항") < text.index("환자를 위한 정보")
    # a left line no longer runs into the right one beside it
    assert "결과자료를 제출하였으며" in text
    assert "결과              재평가" not in text


def test_mfds_asks_for_column_reading():
    assert mfds.PDF_COLUMNS is True


@needs_poppler
def test_without_word_boxes_the_letter_is_read_as_before_and_logged(tmp_path, monkeypatch, caplog):
    from collectors import pdf

    monkeypatch.setattr(pdf, "_bbox_pages", lambda _pdf: None)
    text = _stored_attachment_text(tmp_path)
    assert text == pdf.extract_text(fixture("mfds-letters/sample.pdf"), "ko")[0]
    assert "word boxes were unavailable" in caplog.text
