"""The drug databases probe (collectors/spc/probe_databases.py): what it reports, and what it never prints."""

from __future__ import annotations

from collectors.core.context import SourceBlocked
from collectors.core.models import Fetched
from collectors.spc import probe_databases as pd


class _Ctx:
    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def get(self, url, **kw):
        self.asked.append(url)
        a = self.answers.get(url)
        if isinstance(a, Exception):
            raise a
        return a or Fetched(404, url, b"", "text/html")

    def post(self, url, **kw):
        return self.get(url)


def test_a_list_and_its_label_are_both_reported():
    check = pd.Check("X", "https://x.test/list", r"itemSeq=\d+",
                     follow=(r"itemSeq=(\d+)", "https://x.test/label/{0}", r"<ARTICLE"))
    ctx = _Ctx({"https://x.test/list": Fetched(200, "https://x.test/list", b"<a href='?itemSeq=42'>", "text/html"),
                "https://x.test/label/42": Fetched(200, "https://x.test/label/42", b"<ARTICLE>", "text/xml")})
    r = pd.run_check(ctx, check)
    assert (r.status, r.found, r.label) == ("200", True, "200, label text")


def test_a_bot_check_is_reported_as_blocked_never_retried():
    ctx = _Ctx({"https://x.test/": SourceBlocked("bot check at https://x.test/ (HTTP 403)")})
    r = pd.run_check(ctx, pd.Check("X", "https://x.test/", r"x"))
    assert r.status == "blocked" and not r.found and ctx.asked == ["https://x.test/"]


def test_a_key_in_a_page_is_never_printed():
    key = "s3cr3tKEY=="
    page = f'<script>fetch("https://sfapi.hpra.ie/api/HumanApprovedProducts?code={key}")</script>'.encode()
    check = next(c for c in pd.CHECKS if c.name == "Ireland HPRA key")
    r = pd.run_check(_Ctx({check.url: Fetched(200, check.url, page, "text/html")}), check)
    assert r.found and key not in pd.table([r]) and key not in repr(r)


def test_every_check_has_an_https_address():
    assert all(c.url.startswith("https://") for c in pd.CHECKS)
    assert len({c.name for c in pd.CHECKS}) == len(pd.CHECKS)
