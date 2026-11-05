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


class _Page:
    def __init__(self, final_url: str) -> None:
        self.url = final_url
        self.visited: list[str] = []
        self.closed = False

    def goto(self, url, **_):
        self.visited.append(url)
        return type("R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **k):
        pass

    def content(self):
        return "<html><body>" + "x" * 40000 + "</body></html>"

    def close(self):
        self.closed = True


class _Browser:
    def __init__(self, final_url: str) -> None:
        self.page = _Page(final_url)

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
