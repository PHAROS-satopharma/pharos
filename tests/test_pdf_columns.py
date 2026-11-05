"""PHAROS — two-column PDF pages (Japanese 添付文書) read column by column.

The real insert ``tests/fixtures/spc-pmda/insert_870276_2190417A1029_2_04.pdf`` (イブリーフ静注20mg,
PMDA, revised Oct 2026; saved 5 Nov 2026) is printed in two columns. Read straight across
(``pdftotext -layout``), "9. 特定の背景…" of the right column started a line before "3." of the left
one, so sections 3–8 were never split out. The tests that read a PDF need poppler's ``pdftotext``
(on the CI runner: poppler-utils); the column logic itself is also tested on made-up word boxes.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date

import pytest

from collectors import pdf
from collectors.spc import pmda_pi
from collectors.spc.common import Snapshot
from collectors.spc.run import watch_product
from collectors.spc.sections import normalize, split_japanese
from tests.fakes_a2 import FakeCtx, SpcDb, fixture

INSERT = "spc-pmda/insert_870276_2190417A1029_2_04.pdf"
PID = "870276_2190417A1029_2_04"
PRODUCT = {"id": "33333333-3333-3333-3333-333333333333", "national_id": "870276_2190417A1029",
           "product_name": "イブリーフ静注20mg", "mah": "レコルダティ・レア・ディジーズ・ジャパン株式会社",
           "country_code": "JP", "url": pmda_pi.PDF.format(pid=PID),
           "extra": {"package_id": PID, "pdf_date": "2026年10月27日"}}
INGREDIENT = {"id": "44444444-4444-4444-4444-444444444444", "inn_en": "ibuprofen lysine"}
# One-column PDFs other collectors read: the column reader must leave them exactly as they were.
ONE_COLUMN = ["ansm-securite/sample.pdf", "dkma-dhpc/sample.pdf", "ima-dhpc/sample.pdf",
              "lu-dhpc/sample.pdf", "medsafe-dhcp/sample.pdf", "noma-dhpc/sample.pdf",
              "pmda-revisions/sample.pdf", "swissmedic-hpc/sample.pdf"]


def _poppler() -> bool:
    exe = shutil.which("pdftotext")
    if not exe:
        return False
    proc = subprocess.run([exe, "-v"], capture_output=True, check=False)
    return b"poppler" in (proc.stdout + proc.stderr).lower()


needs_poppler = pytest.mark.skipif(not _poppler(), reason="needs poppler's pdftotext (-bbox)")


def _pmda_ctx() -> FakeCtx:
    return FakeCtx({pmda_pi.PDF.format(pid=PID): INSERT})


# ───────────────────────────── the real insert ─────────────────────────────


@needs_poppler
def test_pmda_insert_sections_come_out_in_order_with_their_own_text():
    snap = pmda_pi.snapshot(_pmda_ctx(), PRODUCT)
    assert list(snap.sections) == [
        "ja:2", "ja:3", "ja:4", "ja:5", "ja:6", "ja:7", "ja:8", "ja:9", "ja:10", "ja:11", "ja:14",
        "ja:16", "ja:17", "ja:18", "ja:19", "ja:20", "ja:21", "ja:22", "ja:23", "ja:24", "ja:26",
        "ja:revision"]
    s = {k: normalize(v) for k, v in snap.sections.items()}
    assert s["ja:4"] == "下記疾患で保存療法（水分制限、利尿剤投与等）が無効の場合 未熟児動脈管開存症"
    assert s["ja:5"] == "未熟性を伴う新生児に対して投与すること。"
    assert s["ja:6"].startswith("通常3回、イブプロフェンとして初回は10mg/kg")
    assert s["ja:7"].startswith("7.1 投与時間の上限は1時間を目安とすること。")
    # 8 (right column) holds 8.1–8.5 and nothing of 2 (left column, same lines on the page)
    assert s["ja:8"].startswith("8.1 本剤の使用にあたっては") and s["ja:8"].endswith(
        "8.5 他のプロスタグランジン合成阻害剤と同時に投与しないこと。")
    assert "2.1" not in s["ja:8"] and "8.1" not in s["ja:2"]
    # 10 is its own text: the interaction table, not 3 or 4 of the left column
    assert s["ja:10"].startswith("本剤は主に肝代謝酵素CYP2C9によって代謝される。 10.2 併用注意")
    assert "ワルファリン等" in s["ja:10"] and "一酸化窒素" in s["ja:10"]
    assert "組成" not in s["ja:10"] and "効能" not in s["ja:10"] and "11.1" not in s["ja:10"]
    assert "10." not in s["ja:3"] and "相互作用" not in s["ja:3"]
    # 11 runs on from the foot of the right column of page 1 to the top of page 2
    assert s["ja:11"].startswith("次の副作用があらわれることがあるので")
    assert "11.1.6 中毒性表皮壊死融解症" in s["ja:11"] and "14.1" not in s["ja:11"]
    assert s["ja:24"].startswith("及び問い合わせ先")          # "＊24." carries a revision mark
    assert snap.sections["ja:revision"] == "2026年10月改訂"
    assert snap.method == pmda_pi.COLUMNS


@needs_poppler
def test_without_word_boxes_the_insert_is_read_as_before(monkeypatch):
    monkeypatch.setattr(pdf, "_bbox_pages", lambda _pdf: None)
    content = fixture(INSERT)
    text, method, words, by_columns = pdf.extract_text_by_columns(content, "ja")
    assert not by_columns and (text, method, words) == pdf.extract_text(content, "ja")
    assert pmda_pi.snapshot(_pmda_ctx(), PRODUCT).method == pmda_pi.LAYOUT


@needs_poppler
@pytest.mark.parametrize("rel", ONE_COLUMN)
def test_one_column_pdfs_extract_exactly_as_before(rel):
    content = fixture(rel)
    text, method, words, by_columns = pdf.extract_text_by_columns(content, None)
    assert by_columns and words > 0
    assert (text, method, words) == pdf.extract_text(content, None)


# ───────────────────────────── re-baseline after the change ─────────────────────────────


class _Then:
    """``snapshot`` answers the prepared snapshots first, then the real PMDA module."""

    def __init__(self, *snaps: Snapshot) -> None:
        self.snaps = list(snaps)

    def snapshot(self, ctx, product):
        return self.snaps.pop(0) if self.snaps else pmda_pi.snapshot(ctx, product)


@needs_poppler
def test_first_column_read_is_a_new_baseline_and_a_later_change_still_alerts():
    db, ctx = SpcDb(), _pmda_ctx()
    # What the label watch stored before this change: the straight-across reading, no method.
    text, _m, _w = pdf.extract_text(fixture(INSERT), "ja")
    old = Snapshot(sections=split_japanese(text), doc_date=date(2026, 10, 27), lang="ja",
                   source_url=PRODUCT["url"])
    module = _Then(old)
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    assert len(db.snapshots) == 1

    # First read by columns: other section texts, but a new baseline — no change, no issue.
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    assert len(db.snapshots) == 2 and not db.changes and not db.issues

    # The same insert again: nothing.
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    assert len(db.snapshots) == 2 and not db.changes

    # A real change in 副作用 after that alerts, diffed against the column reading.
    now = pmda_pi.snapshot(ctx, PRODUCT)
    now.sections["ja:11"] += "\n11.1.7 アナフィラキシー（頻度不明）"
    issue = watch_product(db, ctx, _Then(now), "spc-pmda", PRODUCT, INGREDIENT)
    assert issue is not None and len(db.issues) == 1
    assert db.changes[-1]["s"] == ["ja:11"]
    assert db.changes[-1]["f"] == db.snapshots[1]["id"]


# ───────────────────────────── the column logic on made-up pages ─────────────────────────────


def _line(x0: float, x1: float, y: float, text: str) -> pdf.Word:
    return (x0, y, x1, y + 10, text)


def test_two_column_page_reads_left_then_right_between_full_width_lines():
    words = [_line(200, 400, 10, "TITLE")]                         # crosses the middle
    words += [_line(240, 296, 25, "ドラッグ"), _line(304, 360, 25, "注射液")]   # centred, split
    for i in range(10):
        words.append(_line(50, 280, 50 + 12 * i, f"L{i}"))
        words.append(_line(320, 550, 47 + 12 * i, f"R{i}"))       # baselines a little higher
    words.append(_line(50, 550, 200, "FULL WIDTH TABLE ROW"))
    words += [_line(50, 280, 220, "L-after"), _line(320, 550, 220, "R-after")]
    g = pdf._gutter(words, 600)
    assert g is not None and 280 <= g <= 320
    lines = [x for x in pdf._column_page(words, g).split("\n") if x]
    assert lines == ["TITLE", "ドラッグ 注射液", *[f"L{i}" for i in range(10)],
                     *[f"R{i}" for i in range(10)], "FULL WIDTH TABLE ROW", "L-after", "R-after"]


def test_one_column_pages_have_no_gutter():
    # Japanese: one long word per line across the middle.
    assert pdf._gutter([_line(50, 550 - (i % 4) * 30, 20 + 12 * i, "本文") for i in range(40)],
                       600) is None
    # Latin script: words of uneven widths with spaces that never line up into a strip.
    words = []
    for i in range(40):
        x = 50.0
        while x < 540:
            w = 18 + (i * 7 + int(x)) % 23
            words.append(_line(x, min(x + w, 550), 20 + 12 * i, "word"))
            x += w + 3
    assert pdf._gutter(words, 600) is None
    # Short lines all on the left, nothing beside them.
    assert pdf._gutter([_line(50, 200, 20 + 12 * i, "短い") for i in range(40)], 600) is None


# ───────────────────────────── headings ─────────────────────────────


def test_split_japanese_heading_with_revision_mark_and_after_page_break():
    text = "8. 重要な基本的注意\n8.1 注意A\n－1－\f 9. 特定の背景を有する患者に関する注意\n9.1 注意B\n" \
           "＊＊11. 副作用\n＊＊11.1.6 中毒性表皮壊死融解症"
    got = split_japanese(text)
    assert got["ja:8"] == "8.1 注意A\n－1－"
    assert got["ja:9"] == "9.1 注意B"
    assert got["ja:11"] == "＊＊11.1.6 中毒性表皮壊死融解症"


def test_a_revision_published_while_the_reading_changed_still_alerts():
    # Stored before: the straight-across reading of the 27 Oct insert. The first column read finds a
    # newer revision with a new 副作用 line: compared with the old reading, never a silent baseline.
    db, ctx = SpcDb(), _pmda_ctx()
    old = Snapshot(sections={"ja:2": "2. 禁忌 本剤の成分に対し過敏症", "ja:11": "11. 副作用 発疹"},
                   doc_date=date(2026, 10, 27), lang="ja", source_url=PRODUCT["url"])
    new = Snapshot(sections={"ja:2": "2. 禁忌 本剤の成分に対し過敏症",
                             "ja:11": "11. 副作用 発疹\n11.1.7 アナフィラキシー（頻度不明）"},
                   doc_date=date(2026, 11, 20), lang="ja", source_url=PRODUCT["url"],
                   method=pmda_pi.COLUMNS)
    module = _Then(old, new)
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    issue = watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT)
    assert issue is not None and len(db.issues) == 1
    assert db.changes[-1]["s"] == ["ja:11"]


def test_a_revision_reported_under_the_other_reading_is_not_reported_twice():
    # Read by columns (27 Oct), once straight across (20 Nov: revised, alerts), then by columns again
    # (20 Nov): the revision was already reported; the 27 Oct column reading is not compared again.
    db, ctx = SpcDb(), _pmda_ctx()

    def snap(when, method, side_effects):
        return Snapshot(sections={"ja:11": f"11. 副作用 {side_effects}"}, doc_date=when, lang="ja",
                        source_url=PRODUCT["url"], method=method)

    module = _Then(snap(date(2026, 10, 27), pmda_pi.COLUMNS, "発疹"),
                   snap(date(2026, 11, 20), pmda_pi.LAYOUT, "発疹 アナフィラキシー"),
                   snap(date(2026, 11, 20), pmda_pi.COLUMNS, "発疹 アナフィラキシー"),
                   snap(date(2026, 12, 4), pmda_pi.COLUMNS, "発疹 アナフィラキシー 肝機能障害"))
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is not None
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is None
    assert len(db.issues) == 1 and len(db.snapshots) == 3
    # a later revision read by columns is compared with the column reading of 20 Nov
    assert watch_product(db, ctx, module, "spc-pmda", PRODUCT, INGREDIENT) is not None
    assert len(db.issues) == 2 and "肝機能障害" in str(db.changes[-1]["d"])
