"""FetchContext: waiting out a "slow down" (429/503), and the refusals that mean "blocked", not "down".
All traffic goes through httpx.MockTransport or a stub browser; nothing leaves the machine, nothing sleeps."""

from __future__ import annotations

import httpx
import pytest

from collectors.core.archive import Archive
from collectors.core.context import FetchContext, FetchError, SourceBlocked


def make_ctx(tmp_path, handler) -> tuple[FetchContext, list[float]]:
    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(handler), host_gap_s=0)
    sleeps: list[float] = []
    ctx._sleep = sleeps.append
    return ctx, sleeps


def test_429_is_waited_out_with_retry_after_then_succeeds(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="Too many requests")
        return httpx.Response(200, headers={"content-type": "application/json"}, text="{}")

    ctx, sleeps = make_ctx(tmp_path, handler)
    got = ctx.get("https://www.ema.europa.eu/en/x.json")
    assert got.status == 200 and len(calls) == 2
    assert 7.0 in sleeps                                  # Retry-After was honoured
    assert ctx._host_gap["www.ema.europa.eu"] == 1.0      # that host is now asked more gently


def test_429_without_retry_after_gives_up_after_two_retries(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, text="Too many requests")

    ctx, sleeps = make_ctx(tmp_path, handler)
    with pytest.raises(FetchError) as err:
        ctx.get("https://www.ema.europa.eu/en/y.json")
    assert err.value.status == 429 and len(calls) == 3
    assert [s for s in sleeps if s >= 30] == [30.0, 60.0]
    assert ctx.first_status == 429


def test_fda_abuse_detection_redirect_is_blocked_not_down(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/apology_objects/"):
            return httpx.Response(404, headers={"content-type": "text/html"}, text="<html>Sorry</html>")
        return httpx.Response(302, headers={"location": "https://www.fda.gov/apology_objects/abuse-detection-apology.html"})

    ctx, _ = make_ctx(tmp_path, handler)
    with pytest.raises(SourceBlocked):
        ctx.get("https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/rss.xml")


class _Page:
    def __init__(self, error: str) -> None:
        self.error = error
        self.closed = False

    def goto(self, url, **_):
        raise RuntimeError(self.error)

    def close(self):
        self.closed = True


class _Browser:
    def __init__(self, error: str) -> None:
        self.page = _Page(error)

    def new_page(self, **_):
        return self.page


def test_browser_http2_reset_is_blocked_and_the_page_is_closed(tmp_path):
    ctx, _ = make_ctx(tmp_path, lambda req: httpx.Response(200))
    browser = _Browser("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://www.tga.gov.au/news/safety-alerts")
    ctx._browser = browser
    with pytest.raises(SourceBlocked):
        ctx.browser_get("https://www.tga.gov.au/news/safety-alerts")
    assert browser.page.closed


def test_other_browser_errors_still_fail(tmp_path):
    ctx, _ = make_ctx(tmp_path, lambda req: httpx.Response(200))
    ctx._browser = _Browser("Page.goto: Timeout 45000ms exceeded.")
    with pytest.raises(RuntimeError):
        ctx.browser_get("https://example.test/")
