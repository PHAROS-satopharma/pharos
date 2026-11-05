"""FetchContext(public_only=True): a link, or any redirect from it, that points inside a private network
(the cloud metadata endpoint, loopback, a private range) is refused before it is requested. A fake
resolver stands in for DNS and httpx.MockTransport for the network; nothing leaves the machine."""

from __future__ import annotations

import httpx
import pytest

from collectors.core.archive import Archive
from collectors.core.context import PRIVATE_NETWORK_MESSAGE, FetchContext, FetchError, UnsafeAddress
from collectors.core.memstore import MemoryStore
from collectors.probe import run_probe

DNS = {
    "www.regulator.example": ["93.184.216.34"],
    "metadata.test": ["169.254.169.254"],
    "loopback.test": ["127.0.0.1"],
    "loopback6.test": ["::1"],
    "intranet.test": ["10.1.2.3"],
    "mixed.test": ["93.184.216.34", "192.168.1.10"],
    "mapped.test": ["::ffff:127.0.0.1"],
}


def fake_resolve(host: str) -> list[str]:
    if host not in DNS:
        raise OSError(f"no such host {host}")
    return DNS[host]


def make_ctx(tmp_path, handler, *, public_only: bool = True) -> tuple[FetchContext, list[str]]:
    seen: list[str] = []

    def recording(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return handler(req)

    ctx = FetchContext(None, "run", archive=Archive(tmp_path / "archive"),
                       transport=httpx.MockTransport(recording), host_gap_s=0,
                       public_only=public_only)
    ctx._sleep = lambda s: None
    ctx._resolve = fake_resolve
    return ctx, seen


def ok(req: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/plain"}, text="fine")


@pytest.mark.parametrize("url", [
    "http://metadata.test/latest/meta-data/",
    "http://loopback.test/", "http://loopback6.test/", "http://intranet.test/",
    "http://mixed.test/", "http://mapped.test/",
    "http://169.254.169.254/metadata/instance", "http://127.0.0.1:8080/", "http://[::1]/",
    "http://10.0.0.5/", "http://0.0.0.0/", "http://2130706433/", "http://0x7f.1/",
    "http://017700000001/", "http://127.1/",
])
def test_a_private_address_is_refused_before_any_request(tmp_path, url):
    ctx, seen = make_ctx(tmp_path, ok)
    with pytest.raises(UnsafeAddress) as err:
        ctx.get(url)
    assert seen == []
    assert isinstance(err.value, FetchError)       # a scheduled source records an ordinary failure
    assert PRIVATE_NETWORK_MESSAGE in str(err.value)
    ctx.close()


def test_a_public_host_that_redirects_into_the_metadata_endpoint_is_refused_at_the_hop(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "www.regulator.example":
            return httpx.Response(302, headers={"location": "http://metadata.test/latest/meta-data/"})
        return httpx.Response(200, text="SECRET-CREDENTIALS")

    ctx, seen = make_ctx(tmp_path, handler)
    with pytest.raises(UnsafeAddress):
        ctx.get("https://www.regulator.example/news")
    assert seen == ["https://www.regulator.example/news"]   # the second hop never left
    ctx.close()


def test_a_redirect_to_a_literal_private_ip_or_another_scheme_is_refused(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        target = {"/a": "http://169.254.169.254/", "/b": "file:///etc/passwd"}[req.url.path]
        return httpx.Response(301, headers={"location": target})

    ctx, seen = make_ctx(tmp_path, handler)
    for path in ("/a", "/b"):
        with pytest.raises((UnsafeAddress, httpx.UnsupportedProtocol)):
            ctx.get(f"https://www.regulator.example{path}")
    assert [s.rsplit("/", 1)[-1] for s in seen] == ["a", "b"]
    ctx.close()


def test_a_public_host_and_a_public_redirect_are_read_normally(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://www.regulator.example/new"})
        return ok(req)

    ctx, seen = make_ctx(tmp_path, handler)
    got = ctx.get("https://www.regulator.example/old")
    assert got.status == 200 and got.text == "fine"
    assert got.final_url == "https://www.regulator.example/new" and len(seen) == 2
    ctx.close()


def test_an_unresolvable_host_is_an_ordinary_connection_error(tmp_path):
    ctx, seen = make_ctx(tmp_path, ok)
    with pytest.raises(httpx.ConnectError):
        ctx.get("https://nowhere.test/")
    assert seen == []
    ctx.close()


def test_without_public_only_nothing_changes(tmp_path):
    def boom(host):
        raise AssertionError("no lookup when public_only is off")

    ctx, seen = make_ctx(tmp_path, ok, public_only=False)
    ctx._resolve = boom
    assert ctx.get("http://127.0.0.1:8080/").status == 200
    assert ctx.get("http://metadata.test/").status == 200
    assert len(seen) == 2
    ctx.close()


def test_the_default_is_off():
    ctx = FetchContext(None, "run", archive=Archive(enabled=False))
    try:
        assert ctx.public_only is False
    finally:
        ctx.close()


class _Request:
    def __init__(self, url: str, redirected: bool) -> None:
        self.url = url
        self.redirected_from = object() if redirected else None


class _Route:
    def __init__(self, request: _Request, log: dict[str, str]) -> None:
        self.request, self._log = request, log

    def continue_(self):
        self._log[self.request.url] = "continue"

    def abort(self, code=None):
        self._log[self.request.url] = "abort"


class _Page:
    """``requests``: (url, is a redirect hop) the page makes while loading. Like Playwright, the route
    handler never sees a redirect hop; the request event sees every request."""

    def __init__(self, final_url: str, requests: tuple = ()) -> None:
        self.url = final_url
        self.visited: list[str] = []
        self.closed = False
        self.requests = requests
        self.routed: dict[str, str] = {}
        self._route = None
        self._listeners: list = []

    def route(self, pattern, handler):
        self._route = handler

    def on(self, event, callback):
        if event == "request":
            self._listeners.append(callback)

    def goto(self, url, **_):
        self.visited.append(url)
        for req_url, redirected in self.requests:
            request = _Request(req_url, redirected)
            for callback in self._listeners:
                callback(request)
            if not redirected and self._route is not None:
                self._route(_Route(request, self.routed))
        return type("R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **k):
        pass

    def content(self):
        return "<html><body>" + "x" * 40000 + "</body></html>"

    def close(self):
        self.closed = True


class _Browser:
    def __init__(self, final_url: str, requests: tuple = ()) -> None:
        self.page = _Page(final_url, requests)

    def new_page(self, **_):
        return self.page


def test_the_browser_never_opens_a_private_address(tmp_path):
    ctx, _ = make_ctx(tmp_path, ok)
    ctx._browser = _Browser("http://metadata.test/")
    with pytest.raises(UnsafeAddress):
        ctx.browser_get("http://metadata.test/")
    assert ctx._browser.page.visited == []
    ctx._browser = None
    ctx.close()


def test_the_browser_hands_back_nothing_after_a_redirect_inside(tmp_path):
    ctx, _ = make_ctx(tmp_path, ok)
    ctx._browser = browser = _Browser("http://169.254.169.254/latest/")
    with pytest.raises(UnsafeAddress):
        ctx.browser_get("https://www.regulator.example/page")
    assert browser.page.closed and ctx.first_status is None
    ctx._browser = None
    ctx.close()


def test_probe_of_a_link_into_a_private_network_fails_with_a_plain_message(tmp_path):
    store = MemoryStore()
    store.update_probe("p1", url="http://metadata.test/latest/meta-data/", status="queued")
    ctx, seen = make_ctx(tmp_path, ok)
    try:
        result = run_probe(store, ctx, "p1")
    finally:
        ctx.close()
    assert result["status"] == "failed"
    assert result["error"] == PRIVATE_NETWORK_MESSAGE
    assert seen == []


def test_the_probe_and_the_scheduled_run_turn_public_only_on(tmp_path, monkeypatch):
    from collectors import run as run_mod

    monkeypatch.chdir(tmp_path)
    made: list[dict] = []
    real = run_mod.FetchContext

    def spy(*args, **kwargs):
        made.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(run_mod, "FetchContext", spy)
    monkeypatch.setattr(run_mod.Runner, "run", lambda self, sources: True)
    monkeypatch.setattr(run_mod.Notifier, "digest_if_due", lambda self: None)
    run_mod.main(["--no-db", "--source", "ema-psusa"])

    import collectors.probe as probe_mod
    monkeypatch.setattr(probe_mod, "run_probe", lambda store, ctx, pid: {"status": "ok"})
    run_mod.main(["--no-db", "--probe-id", "p1"])
    assert len(made) == 2 and all(kw.get("public_only") is True for kw in made)


def test_the_browser_blocks_the_pages_own_requests_into_a_private_network(tmp_path):
    ctx, _ = make_ctx(tmp_path, ok)
    meta = "http://169.254.169.254/metadata/instance?api-version=2021-02-01"
    ctx._browser = browser = _Browser("https://www.regulator.example/page", requests=(
        ("https://www.regulator.example/app.js", False), (meta, False),
        ("http://metadata.test/latest/", False), ("data:text/plain,x", False)))
    assert ctx.browser_get("https://www.regulator.example/page").status == 200
    assert browser.page.routed == {"https://www.regulator.example/app.js": "continue", meta: "abort",
                                   "http://metadata.test/latest/": "abort", "data:text/plain,x": "continue"}
    ctx._browser = None
    ctx.close()


def test_the_browser_hands_back_nothing_when_a_request_was_redirected_inside(tmp_path):
    ctx, _ = make_ctx(tmp_path, ok)
    ctx._browser = _Browser("https://www.regulator.example/page",
                            requests=(("http://metadata.test/latest/", True),))
    with pytest.raises(UnsafeAddress):
        ctx.browser_get("https://www.regulator.example/page")
    ctx._browser = None
    ctx.close()


def test_a_name_that_rebinds_after_the_check_never_connects_inside(tmp_path, monkeypatch):
    import httpcore

    from collectors.core import context as context_mod

    connected: list[str] = []

    def connect(self, host, port, **kw):
        connected.append(host)
        raise httpcore.ConnectError("no network in the tests")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    ctx = FetchContext(None, "run", archive=Archive(enabled=False), host_gap_s=0, public_only=True)
    assert isinstance(ctx._client._transport._pool._network_backend, context_mod._PinnedBackend)
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])    # public for the check, then inside
    ctx._resolve = lambda host: next(answers)
    ctx._sleep = lambda s: None
    try:
        with pytest.raises(UnsafeAddress):
            ctx.get("http://rebind.test/")
    finally:
        ctx.close()
    assert connected == []                                  # the socket never opened


def test_the_connection_goes_to_the_address_that_was_checked(monkeypatch):
    import httpcore

    from collectors.core import context as context_mod

    connected: list[tuple[str, int]] = []
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp",
                        lambda self, host, port, **kw: connected.append((host, port)) or "stream")
    backend = context_mod._PinnedBackend(lambda: fake_resolve)
    assert backend.connect_tcp("www.regulator.example", 443) == "stream"
    assert connected == [("93.184.216.34", 443)]
    with pytest.raises(UnsafeAddress):
        backend.connect_tcp("mixed.test", 443)
    assert connected == [("93.184.216.34", 443)]
