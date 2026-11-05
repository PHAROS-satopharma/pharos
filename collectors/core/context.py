"""FetchContext: the only way a parser reaches the network.

* polite: one request at a time per host, at least 1 s apart, a real browser User-Agent, 40 s timeout;
  a 429 or 503 ("slow down") is waited out (its Retry-After, else 30 s, then 60 s) and retried twice,
  and that host's gap is doubled for the rest of the run (up to 8 s); a GET that stalls (read timeout,
  connection reset) is tried again after 15 s and then after 35 s;
* conditional GET (ETag / Last-Modified) for URLs already fetched in this run — a repeat returns
  status 304 with empty content. Validators are kept in memory per run only: across runs, the
  ``(source_id, external_id)`` dedupe makes a re-read cheap and safe;
* every 200 response is archived (R2, or ``./.archive``) and the result carries its sha256/key;
* ``browser_get`` drives one shared headless Chromium (Playwright), launched lazily. It never solves or
  bypasses a bot check: a challenge page raises ``SourceBlocked``;
* ``public_only=True`` (the scheduled runs and the admin's "Test this link" probe) refuses, with
  ``UnsafeAddress``, any request — the first one and every redirect hop — whose host resolves to an
  address that is not on the public internet (loopback, private, link-local such as the cloud metadata
  endpoint 169.254.169.254, 0.0.0.0, odd numeric forms such as http://2130706433/). The connection is
  then made to the very address that was checked (``_PinnedBackend``), so a name whose DNS answer
  changes between the check and the connection (rebinding) cannot reach inside either; in the browser,
  every request the page makes is checked too, and a page that was redirected inside is never read.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpcore
import httpx

from collectors.core.archive import Archive
from collectors.core.models import Fetched

if TYPE_CHECKING:  # pragma: no cover
    from datetime import datetime

    from collectors.core.db import Db

log = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
TIMEOUT_S = 40.0
HOST_GAP_S = 1.0
MAX_BYTES = 80 * 1024 * 1024  # a single original larger than this is refused
SLOW_DOWN = (429, 503)
RETRY_WAITS_S = (30.0, 60.0)    # without Retry-After; one entry per retry
MAX_RETRY_WAIT_S = 120.0
# A GET whose read timed out or whose connection broke is tried again after each of these waits: one
# stall at a site (bfarm.de, 5 Nov 2026 15:34 Cairo, both readers) is not yet a failed check. The last
# wait outlasts a 30 s DNS answer: www.sfda.gov.sa is an F5 load-balanced name (www.wideip.sfda.gov.sa,
# TTL 30) handing out two servers, 195.189.212.79 and 195.189.213.79, so the last try asks again and may
# reach the other one. Its two failed checks on 5 Nov 2026 were one such stall each, on the first page:
# a 40 s read timeout (16:58 Cairo) and a reset during the TLS handshake (18:25 Cairo).
STALL_RETRY_WAITS_S = (15.0, 35.0)
_STALLS = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
MAX_HOST_GAP_S = 8.0
# A refusal that is not a challenge page but means the same: the site will not serve this network.
_REFUSAL_URLS = ("/apology_objects/abuse-detection",)        # www.fda.gov bot management
_REFUSAL_BROWSER_ERRORS = ("net::ERR_HTTP2_PROTOCOL_ERROR",)  # Akamai reset (www.tga.gov.au)


# ───────────────────────────── secrets out of messages ─────────────────────────────
# Error texts end in source_run.error (readable by every user), in Telegram health alerts and in the
# Actions log, so a URL never carries its credentials there: NCBI/openFDA ``api_key=``, tokens,
# passwords, ``user:pass@`` and the Telegram bot token in ``/bot<id>:<secret>/``.
_SECRET_PARAM = re.compile(
    r"([?&;](?:api[_-]?key|apikey|key|access[_-]?token|token|auth|password|passwd|pwd|secret|"
    r"client[_-]?secret)=)[^&#\s\"'<>]*", re.I)
_URL_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/@\s:]+:[^/@\s]*@", re.I)
_BOT_TOKEN = re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+")
REDACTED = "<redacted>"


def redact(text: Any) -> str:
    """``text`` (a URL, an error message, a traceback) with every secret replaced by <redacted>."""
    s = str(text)
    s = _SECRET_PARAM.sub(r"\1" + REDACTED, s)
    s = _URL_USERINFO.sub(r"\1" + REDACTED + "@", s)
    return _BOT_TOKEN.sub(r"\1" + REDACTED, s)


class RedactingFilter(logging.Filter):
    """A handler filter: the formatted message (and traceback) of every record, redacted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string still logs, as is
            message = str(record.msg)
        record.msg, record.args = redact(message), None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


def install_log_redaction() -> None:
    """Called once after ``logging.basicConfig``: httpx/httpcore log every request URL at INFO
    (``api.telegram.org/bot<TOKEN>/…``, ``…&api_key=…``), so they log warnings only, and every root
    handler redacts what it writes."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


class SourceBlocked(Exception):
    """A bot check or challenge page: source health becomes 'blocked', never retried aggressively."""

    def __init__(self, message: Any = "") -> None:
        super().__init__(redact(message))


class ParseError(Exception):
    """The page changed shape; source health becomes 'degraded'."""

    def __init__(self, message: Any = "") -> None:
        super().__init__(redact(message))


class NotSetUp(ParseError):
    """The source has no reading rules yet (its page was never seen); nothing is fetched."""


class FetchError(Exception):
    """An HTTP error status (4xx/5xx) that is not a bot check. Counts as a source failure."""

    def __init__(self, status: int, url: str, message: str | None = None) -> None:
        super().__init__(redact(message or f"HTTP {status} for {url}"))
        self.status = status
        self.url = redact(url)


PRIVATE_NETWORK_MESSAGE = "That address points inside a private network, so it cannot be read."


class UnsafeAddress(FetchError):
    """A URL (or a redirect hop) whose host is not on the public internet. Never requested; counts as
    an ordinary source failure."""

    def __init__(self, url: str, detail: str) -> None:
        super().__init__(0, url, f"{PRIVATE_NETWORK_MESSAGE} ({detail})")


# ───────────────────────────── public addresses only ─────────────────────────────
_NUMERIC_LABEL = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$", re.I)


def _default_resolve(host: str) -> list[str]:
    """Every address ``host`` resolves to (the same lookup httpx's connection makes)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def _is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # an IPv4 address carried inside IPv6 is judged as that IPv4 address
        inner = ip.ipv4_mapped or ip.sixtofour
        if inner is not None:
            ip = inner
    return ip.is_global and not ip.is_multicast


def check_public_host(url: str, host: str | None,
                      resolve: Callable[[str], list[str]] = _default_resolve) -> list[str]:
    """Raise ``UnsafeAddress`` unless ``host`` is a name or address on the public internet; else return
    its addresses. A name that does not resolve raises ``httpx.ConnectError`` (what the request itself
    would have raised)."""
    host = (host or "").strip().rstrip(".").lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        raise UnsafeAddress(url, "no host")
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_public(host):
            raise UnsafeAddress(url, f"{host} is not a public address")
        return [host]
    if _NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]):
        # 2130706433, 0x7f.1, 017700000001, 127.1: resolvers read these as IP addresses
        raise UnsafeAddress(url, f"{host} is an unusual numeric address")
    try:
        addresses = resolve(host)
    except (OSError, UnicodeError) as exc:
        raise httpx.ConnectError(f"cannot resolve {host}: {exc}") from None
    if not addresses:
        raise httpx.ConnectError(f"cannot resolve {host}")
    bad = [a for a in addresses if not _is_public(a)]
    if bad:
        raise UnsafeAddress(url, f"{host} resolves to {bad[0]}")
    return addresses


class _PinnedBackend(httpcore.SyncBackend):
    """httpx's network layer for ``public_only``: the host is resolved and checked here, once, and the
    socket goes to one of those checked addresses. TLS still names the host (SNI and the certificate
    check use the request's host, not the address)."""

    def __init__(self, resolve: Callable[[], Callable[[str], list[str]]]) -> None:
        self._resolve = resolve   # read at connect time: the context's resolver is replaceable

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options: Any = None) -> Any:
        addresses = check_public_host(f"tcp://{host}:{port}", host, self._resolve())
        error: Exception | None = None
        for address in dict.fromkeys(addresses):
            try:
                return super().connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                           socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or httpcore.ConnectError(f"cannot connect to {host}")


# Markers of Cloudflare / bot-management interstitials, checked on the first 64 KB of a page.
# Strong markers only ever appear on an interstitial. Weak ones (the challenge script, a captcha
# iframe) are also injected into ordinary pages behind Cloudflare, so they count only on an error
# status or on a page too small to be the real listing.
_STRONG = [re.compile(p, re.I) for p in (
    r"<title>\s*Just a moment\.{0,3}\s*</title>", r"Performing security verification",
    r"Attention Required! \| Cloudflare", r"id=\"challenge-form\"", r"id=\"cf-challenge",
    r"Checking your browser before accessing", r"Request unsuccessful\. Incapsula",
    r"_Incapsula_Resource", r"/_sec/cp_challenge/", r"id=\"px-captcha\"",
    r"Verify you are human",
    # F5 BIG-IP ASM "TSPD" JavaScript interstitial (famhp.be / afmps.be / fagg.be, Nov 2026)
    r"href=\"/TSPD/\?type=", r"window\[\"bobcmn\"\]",
)]
_WEAK = [re.compile(p, re.I) for p in (
    r"cf-chl", r"cf_chl_opt", r"challenge-platform",
    r"<iframe[^>]+(?:hcaptcha|recaptcha|turnstile|captcha)", r"class=\"g-recaptcha\"",
    r"cf-turnstile",
)]
_SMALL_PAGE = 30000


def looks_like_challenge(text: str, status: int | None = None, headers: Any = None) -> bool:
    head = text[:65536]
    if any(rx.search(head) for rx in _STRONG):
        return True
    if headers is not None and headers.get("cf-mitigated") == "challenge":
        return True
    if (status is not None and status != 200) or len(text) < _SMALL_PAGE:
        return any(rx.search(head) for rx in _WEAK)
    return False


class FetchContext:
    """Shared by every parser in one run. Not thread-safe (the runner is sequential)."""

    def __init__(self, db: "Db | None", run_id: str, *, backfill: bool = False,
                 archive: Archive | None = None, dry_run: bool = False,
                 transport: httpx.BaseTransport | None = None,
                 host_gap_s: float = HOST_GAP_S, public_only: bool = False) -> None:
        self.db = db
        self.run_id = run_id
        self.backfill = backfill
        self.dry_run = dry_run
        self.archiver = archive if archive is not None else Archive()
        self.host_gap_s = host_gap_s
        # Refuse hosts that are not on the public internet (see the module docstring); the resolver is
        # replaceable so tests never reach real DNS.
        self.public_only = public_only
        self._resolve: Callable[[str], list[str]] = _default_resolve
        if transport is None and public_only:
            transport = httpx.HTTPTransport(http2=False)
            transport._pool._network_backend = _PinnedBackend(lambda: self._resolve)
        self._client = httpx.Client(
            follow_redirects=True, timeout=httpx.Timeout(TIMEOUT_S),
            headers={"User-Agent": USER_AGENT, "Accept-Language": "*;q=0.5"},
            transport=transport, http2=False,
            # httpx calls request hooks before EVERY request it sends, each redirect hop included
            event_hooks={"request": [self._guard_request]},
        )
        self._last_hit: dict[str, float] = {}
        self._host_gap: dict[str, float] = {}
        self._sleep = time.sleep
        self._validators: dict[str, tuple[str | None, str | None]] = {}
        self.archived: dict[str, tuple[str | None, str | None, str, int]] = {}
        self._playwright = None
        self._browser = None
        # English INNs of the active ingredients, set by the runner (PubMed searches them).
        self.watchlist: list[str] = []
        # How far back a backfill reads (app_setting backfill_months or --backfill N).
        self.backfill_months: int = 12
        # When the current source was last read completely (set by the runner before each source).
        self.last_ok_at: datetime | None = None
        # Per-source bookkeeping the runner reads (http_status of the first request).
        self.first_status: int | None = None
        self.requests = 0

    # ───────────────────────────── bookkeeping ─────────────────────────────
    def begin_source(self) -> None:
        self.first_status = None
        self.requests = 0

    def _note_status(self, status: int) -> None:
        self.requests += 1
        if self.first_status is None:
            self.first_status = status

    def _guard_request(self, request: httpx.Request) -> None:
        if not self.public_only:
            return
        url = str(request.url)
        if request.url.scheme not in ("http", "https"):
            raise UnsafeAddress(url, f"{request.url.scheme}: links are not read")
        check_public_host(url, request.url.host, self._resolve)

    def _check_url(self, url: str) -> None:
        """The public-only check for a URL fetched outside httpx (the browser)."""
        if not self.public_only:
            return
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https"):
            raise UnsafeAddress(url, f"{parts.scheme or 'no'} scheme: links are not read")
        check_public_host(url, parts.hostname, self._resolve)

    def _polite(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        last = self._last_hit.get(host)
        if last is not None:
            wait = self._host_gap.get(host, self.host_gap_s) - (time.monotonic() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_hit[host] = time.monotonic()

    def _slow_down(self, url: str, attempt: int, retry_after: str | None) -> float:
        """The host asked us to slow down: double its gap, and say how long to wait before retrying."""
        host = urlsplit(url).hostname or ""
        gap = self._host_gap.get(host, self.host_gap_s)
        self._host_gap[host] = min(MAX_HOST_GAP_S, max(1.0, gap * 2))
        wait = RETRY_WAITS_S[min(attempt, len(RETRY_WAITS_S) - 1)]
        if retry_after and retry_after.strip().isdigit():
            wait = float(retry_after.strip())
        return min(wait, MAX_RETRY_WAIT_S)

    # ───────────────────────────── archive ─────────────────────────────
    def archive(self, content: bytes, mime: str) -> tuple[str, str]:
        """-> (sha256, r2_key)."""
        return self.archiver.put(content, mime)

    def _remember(self, url: str, fetched: Fetched) -> None:
        record = (fetched.sha256, fetched.r2_key, fetched.mime, len(fetched.content))
        self.archived[url] = record
        self.archived[fetched.final_url] = record

    def archived_for(self, url: str) -> tuple[str | None, str | None, str, int] | None:
        """(sha256, r2_key, mime, bytes) of the 200 response this run got for ``url``, if any."""
        return self.archived.get(url)

    def forget(self, url: str) -> None:
        """Ask for ``url`` in full next time: a reader that needs the body again must not get a bare 304."""
        self._validators.pop(url, None)

    # ───────────────────────────── HTTP ─────────────────────────────
    def get(self, url: str, *, accept: str | None = None, headers: dict | None = None,
            raise_for_status: bool = True) -> Fetched:
        return self.request("GET", url, accept=accept, headers=headers,
                            raise_for_status=raise_for_status)

    def post(self, url: str, *, data: dict | None = None, json: Any = None,
             accept: str | None = None, headers: dict | None = None,
             raise_for_status: bool = True) -> Fetched:
        """POST for the few boards that only answer forms (never used for logins)."""
        return self.request("POST", url, accept=accept, headers=headers, data=data, json=json,
                            raise_for_status=raise_for_status)

    def _read(self, method: str, url: str, hdrs: dict, data: dict | None,
              json: Any) -> tuple[httpx.Response, bytes]:
        """One request, its body read in full (refused past MAX_BYTES)."""
        with self._client.stream(method, url, headers=hdrs, data=data, json=json) as resp:
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise FetchError(resp.status_code, url, f"response over {MAX_BYTES} bytes")
                chunks.append(chunk)
        return resp, b"".join(chunks)

    def request(self, method: str, url: str, *, accept: str | None = None,
                headers: dict | None = None, data: dict | None = None, json: Any = None,
                raise_for_status: bool = True) -> Fetched:
        hdrs = {"Accept": accept or DEFAULT_ACCEPT}
        if headers:
            hdrs.update(headers)
        if method == "GET" and url in self._validators:
            etag, modified = self._validators[url]
            if etag:
                hdrs["If-None-Match"] = etag
            if modified:
                hdrs["If-Modified-Since"] = modified
        stalls = 0
        for attempt in range(len(RETRY_WAITS_S) + 1):
            self._polite(url)
            while True:
                try:
                    resp, content = self._read(method, url, hdrs, data, json)
                    break
                except _STALLS as exc:
                    if method != "GET" or stalls == len(STALL_RETRY_WAITS_S):
                        raise       # a POST is never sent twice; a third stall is the site, not luck
                    wait = STALL_RETRY_WAITS_S[stalls]
                    stalls += 1
                    log.info("%s from %s: waiting %.0f s, then trying again (%d of %d)",
                             type(exc).__name__, redact(url), wait, stalls, len(STALL_RETRY_WAITS_S))
                    self._sleep(wait)
                    self._polite(url)
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            final_url = str(resp.url)
            fetched = Fetched(status, final_url, content, ctype)
            if "html" in ctype.lower() or (status in (403, 429, 503) and content[:1] == b"<"):
                if looks_like_challenge(fetched.text, status, resp.headers):
                    self._note_status(status)
                    raise SourceBlocked(f"bot check at {final_url} (HTTP {status})")
            if status not in SLOW_DOWN or attempt == len(RETRY_WAITS_S):
                break
            wait = self._slow_down(url, attempt, resp.headers.get("retry-after"))
            log.info("HTTP %s from %s: waiting %.0f s, then retrying", status, redact(final_url),
                     wait)
            self._sleep(wait)
        self._note_status(status)
        if any(marker in final_url for marker in _REFUSAL_URLS):
            raise SourceBlocked(f"the site refused this network: redirected to {final_url}")
        if status == 304:
            return Fetched(304, final_url, b"", ctype)
        if status == 200:
            if method == "GET":
                self._validators[url] = (resp.headers.get("etag"), resp.headers.get("last-modified"))
            fetched.sha256, fetched.r2_key = self.archive(content, fetched.mime)
            self._remember(url, fetched)
        elif raise_for_status and status >= 400:
            raise FetchError(status, final_url)
        return fetched

    # ───────────────────────────── browser ─────────────────────────────
    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        return self._browser

    def browser_get(self, url: str, *, wait_selector: str | None = None,
                    timeout_ms: int = 45000, before_wait: Callable[[Any], None] | None = None) -> Fetched:
        """``before_wait(page)`` runs once the page has loaded, before ``wait_selector`` is awaited
        (e.g. ticking a site's information disclaimer the owner agreed PHAROS may accept)."""
        self._check_url(url)
        browser = self._ensure_browser()
        self._polite(url)
        page = browser.new_page(user_agent=USER_AGENT, locale="en-GB")
        inside: list[str] = []      # redirect hops into a private network (a route never sees those)
        if self.public_only:
            page.route("**/*", self._browser_guard)
            page.on("request", lambda req: self._browser_hop(req, inside))
        try:
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as exc:  # noqa: BLE001 - Playwright raises its own Error type
                if any(marker in str(exc) for marker in _REFUSAL_BROWSER_ERRORS):
                    raise SourceBlocked(f"the site refused this network at {url} "
                                        f"({str(exc).splitlines()[0][:200]})") from None
                raise
            status = response.status if response is not None else 0
            if before_wait is not None:
                before_wait(page)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception:  # noqa: BLE001 - a missing selector is checked below
                    html = page.content()
                    if looks_like_challenge(html, status):
                        raise SourceBlocked(f"bot check at {page.url}") from None
                    raise ParseError(f"selector {wait_selector!r} never appeared at {page.url}") from None
            else:
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
                except Exception:  # noqa: BLE001 - busy pages never go idle; content is enough
                    pass
            html = page.content()
            final_url = page.url
        finally:
            page.close()
        # The browser follows redirects itself: a page that ended up inside a private network, or whose
        # own requests were redirected there, is not handed back (the request was made; its content is
        # never read).
        if inside:
            raise UnsafeAddress(inside[0], "a redirect from the page led inside")
        if self.public_only and urlsplit(final_url).scheme.lower() in ("http", "https"):
            check_public_host(final_url, urlsplit(final_url).hostname, self._resolve)
        self._note_status(status)
        if looks_like_challenge(html, status):
            raise SourceBlocked(f"bot check at {final_url} (HTTP {status})")
        content = html.encode("utf-8")
        fetched = Fetched(status, final_url, content, "text/html; charset=utf-8")
        if status == 200:
            fetched.sha256, fetched.r2_key = self.archive(content, "text/html")
            self._remember(url, fetched)
        elif status >= 400:
            raise FetchError(status, final_url)
        return fetched

    def _browser_safe(self, url: str) -> bool:
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            return True   # data:, blob: and the like never leave the browser
        try:
            self._check_url(url)
        except (UnsafeAddress, httpx.ConnectError):
            return False
        return True

    def _browser_guard(self, route: Any) -> None:
        """Every request the page makes (scripts, frames, fetch/XHR) passes the public-only check first."""
        if self._browser_safe(route.request.url):
            route.continue_()
        else:
            log.warning("browser: refused a request inside a private network: %s", redact(route.request.url))
            route.abort("blockedbyclient")

    def _browser_hop(self, request: Any, inside: list[str]) -> None:
        if request.redirected_from is not None and not self._browser_safe(request.url):
            inside.append(request.url)

    def close(self) -> None:
        try:
            self._client.close()
        finally:
            if self._browser is not None:
                try:
                    self._browser.close()
                finally:
                    self._playwright.stop()
                    self._browser = None
                    self._playwright = None

    def __enter__(self) -> "FetchContext":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
