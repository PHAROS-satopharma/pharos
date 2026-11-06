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


@pytest.mark.parametrize("name", ["challenge_fr.html", "challenge_nl_2026-11-05.html"])
def test_famhp_f5_challenge_pages_read_as_blocked(name):
    from pathlib import Path

    from collectors.core.context import looks_like_challenge
    html = (Path(__file__).parent / "fixtures" / "famhp-news" / name).read_text(encoding="utf-8", errors="replace")
    assert looks_like_challenge(html, 200)


def test_a_real_regulator_page_is_not_a_challenge():
    from pathlib import Path

    from collectors.core.context import looks_like_challenge
    html = (Path(__file__).parent / "fixtures" / "aifa-sicurezza" / "niis_live_2026-11-05.html").read_text(encoding="utf-8")
    assert not looks_like_challenge(html, 200)


# ───────────────────────────── secrets never reach messages or logs ─────────────────────────────

NCBI_KEY = "0123456789abcdef0123456789abcdef0123"
BOT = "bot7123456789:AAH-secretTokenPart_xyz"


def test_redact_hides_url_secrets():
    from collectors.core.context import redact

    url = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=x"
           f"&tool=pharos&api_key={NCBI_KEY}")
    got = redact(f"HTTP 500 for {url}")
    assert NCBI_KEY not in got and "api_key=<redacted>" in got and "db=pubmed&term=x" in got
    for secret_url in (f"https://api.telegram.org/{BOT}/sendMessage",
                       "https://user:hunter2@example.org/x",
                       "https://x.org/a?token=T0K3N&password=pw1&key=K3Y"):
        out = redact(secret_url)
        for secret in ("AAH-secretTokenPart_xyz", "hunter2", "T0K3N", "pw1", "K3Y"):
            assert secret not in out, out


def test_fetch_errors_never_carry_the_api_key(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if "blocked" in req.url.path:
            return httpx.Response(403, headers={"content-type": "text/html"},
                                  text="<html><title>Just a moment...</title></html>")
        return httpx.Response(500, text="oops")

    ctx, _ = make_ctx(tmp_path, handler)
    with pytest.raises(FetchError) as err:
        ctx.get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&api_key={NCBI_KEY}")
    assert NCBI_KEY not in str(err.value) and NCBI_KEY not in err.value.url
    with pytest.raises(SourceBlocked) as blocked:
        ctx.get(f"https://eutils.ncbi.nlm.nih.gov/blocked?api_key={NCBI_KEY}")
    assert NCBI_KEY not in str(blocked.value)


def test_log_redaction_quiets_httpx_and_redacts_records():
    import logging

    from collectors.core.context import install_log_redaction

    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            seen.append(self.format(record))

    root = logging.getLogger()
    handler = Capture()
    root.addHandler(handler)
    levels = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    try:
        install_log_redaction()
        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
        assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
        logging.getLogger("collectors.test").warning(
            "HTTP Request: POST %s", f"https://api.telegram.org/{BOT}/sendMessage")
        try:
            raise RuntimeError(f"failed https://x.org/?api_key={NCBI_KEY}")
        except RuntimeError:
            logging.getLogger("collectors.test").exception("boom")
    finally:
        root.removeHandler(handler)
        for n, lvl in levels.items():
            logging.getLogger(n).setLevel(lvl)
    text = "\n".join(seen)
    assert "AAH-secretTokenPart_xyz" not in text and NCBI_KEY not in text
    assert "api.telegram.org/bot<redacted>/sendMessage" in text


def test_a_read_timeout_is_tried_once_more_then_succeeds(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("The read operation timed out", request=req)
        return httpx.Response(200, headers={"content-type": "application/rss+xml"}, text="<rss/>")

    ctx, sleeps = make_ctx(tmp_path, handler)
    got = ctx.get("https://www.bfarm.de/SiteGlobals/Functions/RSSFeed/x.xml")
    assert got.status == 200 and len(calls) == 2 and 15.0 in sleeps


def test_sfda_reset_twice_is_read_on_the_third_try_after_the_dns_answer_expires(tmp_path):
    # 5 Nov 2026 18:25 Cairo: www.sfda.gov.sa reset the TLS handshake on the first page. Its name is an
    # F5 load balancer with a 30 s DNS answer, so the last try waits past it and may reach the other server.
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("[Errno 104] Connection reset by peer", request=req)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>warnings</html>")

    ctx, sleeps = make_ctx(tmp_path, handler)
    got = ctx.get("https://www.sfda.gov.sa/ar/warnings")
    assert got.status == 200 and len(calls) == 3
    assert 15.0 in sleeps and 35.0 in sleeps and max(sleeps) > 30


def test_a_third_stall_is_reported_and_a_post_is_never_sent_twice(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.method)
        raise httpx.ConnectError("connection reset", request=req)

    ctx, _ = make_ctx(tmp_path, handler)
    with pytest.raises(httpx.ConnectError):
        ctx.get("https://www.bfarm.de/a")
    assert calls == ["GET", "GET", "GET"]
    calls.clear()
    with pytest.raises(httpx.ConnectError):
        ctx.post("https://www.bfarm.de/form", data={"q": "x"})
    assert calls == ["POST"]


def test_a_server_error_is_tried_again_like_a_stall_then_read(tmp_path):
    # openFDA 21:17 and INFARMED 18:20 Cairo, 5 Nov 2026: one 500 that the same request answered straight after.
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(500, text="Internal Server Error")
        if len(calls) == 2:
            return httpx.Response(502, text="Bad Gateway")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>recalls</html>")

    ctx, sleeps = make_ctx(tmp_path, handler)
    got = ctx.get("https://api.fda.gov/drug/enforcement.json")
    assert got.status == 200 and len(calls) == 3
    assert sleeps == [15.0, 35.0]


def test_a_third_server_error_fails_and_post_or_opt_out_is_not_repeated(tmp_path):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.method)
        return httpx.Response(504, text="Gateway Timeout")

    ctx, _ = make_ctx(tmp_path, handler)
    with pytest.raises(FetchError) as err:
        ctx.get("https://www.infarmed.pt/a")
    assert err.value.status == 504 and calls == ["GET", "GET", "GET"]
    calls.clear()
    with pytest.raises(FetchError):
        ctx.post("https://www.infarmed.pt/form", data={"q": "x"})
    assert calls == ["POST"]
    calls.clear()
    with pytest.raises(FetchError):     # PubMed keeps its own, longer schedule
        ctx.get("https://eutils.ncbi.nlm.nih.gov/x", retry_server_errors=False)
    assert calls == ["GET"]


def test_retry_after_zero_still_waits(tmp_path):
    # EMA answered "too many requests"; a Retry-After of 0 must not turn into three requests in a row.
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, text="Too many requests")
        return httpx.Response(200, headers={"content-type": "application/json"}, text="{}")

    ctx, sleeps = make_ctx(tmp_path, handler)
    assert ctx.get("https://www.ema.europa.eu/en/z.json").status == 200
    assert 5.0 in sleeps and 0.0 not in sleeps


def test_the_default_host_gap_is_two_seconds():
    from collectors.core.context import HOST_GAP_S

    assert HOST_GAP_S == 2.0


SECURITY_PAGE = (b"<html><head><title>Security check</title></head><body><h1>One more step</h1>"
                 b"<p>Please complete the captcha below to continue to the site.</p></body></html>")


def test_a_list_page_that_reads_like_a_security_check_is_blocked_not_changed():
    from collectors.core.models import Fetched
    from collectors.parsers._html_util import require

    page = Fetched(200, "https://www.example.gov/alerts", SECURITY_PAGE, "text/html")
    with pytest.raises(SourceBlocked, match="security check"):
        require([], page, marker='id="results"')


def test_a_real_page_that_lost_its_list_is_still_a_parse_error():
    from collectors.core.context import ParseError
    from collectors.core.models import Fetched
    from collectors.parsers._html_util import require

    big = b"<html><body>" + b"<p>news</p>" * 12000 + b"<form>captcha</form></body></html>"
    with pytest.raises(ParseError):         # a large page with a contact-form captcha is not a block page
        require([], Fetched(200, "https://www.example.gov/a", big, "text/html"), marker='id="results"')
    marked = b'<html><div id="results"></div><p>Security check</p></html>'
    with pytest.raises(ParseError):         # the healthy page's marker is there: the list itself changed
        require([], Fetched(200, "https://www.example.gov/b", marked, "text/html"), marker='id="results"')



def test_a_page_that_lost_its_list_with_a_captcha_in_its_code_is_a_parse_error():
    # #90 read "captcha" anywhere in the HTML: a small page whose list moved, with a reCAPTCHA script and
    # widget on its contact form, was reported as a bot check (Sources: "Blocks automated reading").
    from collectors.core.context import ParseError
    from collectors.core.models import Fetched
    from collectors.parsers._html_util import require

    page = (b'<html><head><title>Safety alerts</title>'
            b'<script src="https://www.google.com/recaptcha/api.js"></script></head><body>'
            b'<h1>Safety alerts</h1><div class="new-layout"><article>Alert one</article></div>'
            b'<form id="contact"><div class="g-recaptcha" data-sitekey="x"></div>'
            b'<input name="captcha_token" type="hidden"></form></body></html>')
    with pytest.raises(ParseError) as exc:
        require([], Fetched(200, "https://www.example.gov/alerts", page, "text/html"), marker="div.views-row")
    assert not isinstance(exc.value, SourceBlocked)


def test_the_infarmed_firewall_captcha_still_reads_as_a_bot_check():
    from pathlib import Path

    from collectors.core.context import looks_like_block_page

    html = (Path(__file__).parent / "fixtures/infarmed-circulares/firewall-captcha.html").read_text("utf-8", "replace")
    assert looks_like_block_page(html)
    wordy = ("<html><body><h1>News</h1>" + "<p>A notice about a medicine and its risks.</p>" * 60
             + "<p>Please complete the captcha to subscribe.</p></body></html>")
    assert not looks_like_block_page(wordy)     # a page with much more to say than a security page
