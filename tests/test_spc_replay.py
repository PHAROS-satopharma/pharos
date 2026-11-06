"""A real past revision of a label, replayed through the label watch's change detector (collectors/spc/replay.py).

Corlanor (ivabradine), DailyMed SPL versions 16 and 20: the April 2019 approval for children with heart failure
(tests/fixtures/spc-replay/README.md)."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from collectors.core.models import Fetched
from collectors.spc import replay
from collectors.spc.dailymed import parse_spl
from tests.fakes_a2 import fixture

SETID = "92018a65-38f6-45f7-91d4-a34921b81d0d"


def _zip(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("9f7f886a.xml", xml)
        z.writestr("corlanor-01.jpg", b"\xff\xd8")
    return buf.getvalue()


def test_the_2019_paediatric_revision_alerts_in_the_right_sections():
    before, d16 = parse_spl(fixture("spc-replay/corlanor_v16.xml"))
    after, d20 = parse_spl(fixture("spc-replay/corlanor_v20.xml"))
    assert (d16, d20) == (date(2017, 1, 17), date(2019, 4, 22))
    result = replay.compare(before, after)
    assert {"us:indications", "us:dosage_and_administration", "us:specific_populations",
            "us:warnings_and_precautions", "us:contraindications"} <= set(result["changed"])
    assert "us:indications" not in result["alerting"]           # read, never alerts
    assert {"us:warnings_and_precautions", "us:contraindications", "us:specific_populations",
            "us:adverse_reactions"} <= set(result["alerting"])
    added = " ".join(x["after"] for c in result["changes"] if c["section"] == "us:dosage_and_administration"
                     for x in c["changes"])
    assert "pediatric" in added.lower()


def test_the_same_version_twice_is_no_change():
    sections, _ = parse_spl(fixture("spc-replay/corlanor_v20.xml"))
    assert replay.compare(sections, dict(sections)) == {"changed": [], "alerting": [], "changes": []}


class _Ctx:
    def __init__(self, answers):
        self.answers = answers          # url -> list of bodies, one per request
        self.asked = []

    def forget(self, url):
        pass

    def get(self, url, **kw):
        self.asked.append(url)
        return Fetched(200, url, self.answers[url].pop(0), "application/zip")


def test_a_zip_cut_short_is_asked_for_again():
    whole = _zip(fixture("spc-replay/corlanor_v16.xml"))
    url = replay.DAILYMED_VERSION.format(setid=SETID, version=16)
    ctx = _Ctx({url: [whole[: len(whole) // 2], whole]})
    sections, when = replay.dailymed_version(ctx, SETID, 16)
    assert when == date(2017, 1, 17) and "us:warnings_and_precautions" in sections and len(ctx.asked) == 2


def test_a_version_that_never_comes_whole_is_an_error():
    url = replay.DAILYMED_VERSION.format(setid=SETID, version=16)
    ctx = _Ctx({url: [b"PK\x03\x04cut"] * replay.TRIES})
    with pytest.raises(replay.ReplayError, match="not a whole zip"):
        replay.dailymed_version(ctx, SETID, 16)


def test_replay_reads_both_versions_and_names_them():
    ctx = _Ctx({replay.DAILYMED_VERSION.format(setid=SETID, version=16): [_zip(fixture("spc-replay/corlanor_v16.xml"))],
                replay.DAILYMED_VERSION.format(setid=SETID, version=20): [_zip(fixture("spc-replay/corlanor_v20.xml"))]})
    result = replay.replay_dailymed(ctx, SETID, 16, 20)
    assert result["versions"] == ("16", "20") and result["alerting"]
    assert "Sections that would alert: " in replay.summary(result)
