"""The three EMA list readers (EURD, herbal, literature monitoring) wait out EMA's "429 Too Many Requests"
instead of losing the day's read on the first one (collectors/ema_fetch.py). All traffic goes through
httpx.MockTransport; nothing leaves the machine, nothing sleeps."""

from __future__ import annotations

import httpx
import pytest

from collectors import eurd, herbal, mlm
from collectors.core.context import USER_AGENT, FetchError
from collectors.ema_fetch import ema_context

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def make_ctx(handler):
    ctx = ema_context("test", transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    ctx._sleep = sleeps.append
    return ctx, sleeps


def once_too_many(body: bytes, ctype: str):
    """EMA's answer: 429 to the first request for each URL, the file to the next one."""
    seen: dict[str, int] = {}
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        url = str(req.url)
        seen[url] = seen.get(url, 0) + 1
        if seen[url] == 1:
            return httpx.Response(429, headers={"Retry-After": "11"}, text="Too Many Requests")
        return httpx.Response(200, headers={"content-type": ctype}, content=body)

    return handler, calls


@pytest.mark.parametrize("reader, ctype", [(eurd, XLSX), (herbal, "application/json")])
def test_a_429_is_waited_out_and_the_list_is_read(reader, ctype):
    handler, calls = once_too_many(b"the list", ctype)
    ctx, sleeps = make_ctx(handler)
    with ctx:
        assert reader.download(ctx) == b"the list"
    assert [str(c.url) for c in calls] == [reader.URL, reader.URL]
    assert 11.0 in sleeps                                         # EMA's Retry-After was honoured
    assert all(c.headers["User-Agent"] == USER_AGENT for c in calls)


def test_the_mlm_page_and_its_list_each_wait_out_a_429():
    link = "/en/documents/other/medical-literature-monitoring-substance-groups-1-309-valid-1-june-2020_en.xlsx"
    seen: dict[str, int] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        seen[url] = seen.get(url, 0) + 1
        if seen[url] == 1:
            return httpx.Response(429, text="Too Many Requests")
        if url == mlm.PAGE:
            return httpx.Response(200, headers={"content-type": "text/html"},
                                  text=f'<a href="{link}">Substance groups</a>')
        return httpx.Response(200, headers={"content-type": XLSX}, content=b"the list")

    ctx, sleeps = make_ctx(handler)
    with ctx:
        content, name = mlm.download(ctx)
    assert (content, name) == (b"the list", link.rsplit("/", 1)[-1])
    assert seen == {mlm.PAGE: 2, mlm.HOST + link: 2}
    assert sleeps.count(30.0) == 2                                # no Retry-After: 30 s, once per URL


@pytest.mark.parametrize("reader", [eurd, herbal, mlm])
def test_a_list_ema_keeps_refusing_raises_so_the_step_warns(reader):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(429, text="Too Many Requests")

    ctx, _ = make_ctx(handler)
    with ctx, pytest.raises(FetchError):
        reader.download(ctx)
    assert len(calls) == 3                                        # the first try and two retries, no more
