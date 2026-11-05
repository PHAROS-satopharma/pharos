"""FetchContext: the only way a parser reaches the network.

* polite: one request at a time per host, at least 1 s apart, a real browser User-Agent, 40 s timeout;
  a 429 or 503 ("slow down") is waited out (its Retry-After, else 30 s, then 60 s) and retried twice,
  and that host's gap is doubled for the rest of the run (up to 8 s);
* conditional GET (ETag / Last-Modified) for URLs already fetched in this run — a repeat returns
  status 304 with empty content. Validators are kept in memory per run only: across runs, the
  ``(source_id, external_id)`` dedupe makes a re-read cheap and safe;
* every 200 response is archived (R2, or ``./.archive``) and the result carries its sha256/key;
* ``browser_get`` drives one shared headless Chromium (Playwright), launched lazily. It never solves or
  bypasses a bot check: a challenge page raises ``SourceBlocked``.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from collectors.core.archive import Archive
from collectors.core.models import Fetched

if TYPE_CHECKING:  # pragma: no cover
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
MAX_HOST_GAP_S = 8.0
# A refusal that is not a challenge page but means the same: the site will not serve this network.
_REFUSAL_URLS = ("/apology_objects/abuse-detection",)        # www.fda.gov bot management
_REFUSAL_BROWSER_ERRORS = ("net::ERR_HTTP2_PROTOCOL_ERROR",)  # Akamai reset (www.tga.gov.au)


class SourceBlocked(Exception):
    """A bot check or challenge page: source health becomes 'blocked', never retried aggressively."""


class ParseError(Exception):
    """The page changed shape; source health becomes 'degraded'."""


class FetchError(Exception):
    """An HTTP error status (4xx/5xx) that is not a bot check. Counts as a source failure."""

    def __init__(self, status: int, url: str, message: str | None = None) -> None:
        super().__init__(message or f"HTTP {status} for {url}")
        self.status = status
        self.url = url


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
                 host_gap_s: float = HOST_GAP_S) -> None:
        self.db = db
        self.run_id = run_id
        self.backfill = backfill
        self.dry_run = dry_run
        self.archiver = archive if archive is not None else Archive()
        self.host_gap_s = host_gap_s
        self._client = httpx.Client(
            follow_redirects=True, timeout=httpx.Timeout(TIMEOUT_S),
            headers={"User-Agent": USER_AGENT, "Accept-Language": "*;q=0.5"},
            transport=transport, http2=False,
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
        for attempt in range(len(RETRY_WAITS_S) + 1):
            self._polite(url)
            with self._client.stream(method, url, headers=hdrs, data=data, json=json) as resp:
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise FetchError(resp.status_code, url, f"response over {MAX_BYTES} bytes")
                    chunks.append(chunk)
                content = b"".join(chunks)
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
            log.info("HTTP %s from %s: waiting %.0f s, then retrying", status, final_url, wait)
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
                    timeout_ms: int = 45000) -> Fetched:
        browser = self._ensure_browser()
        self._polite(url)
        page = browser.new_page(user_agent=USER_AGENT, locale="en-GB")
        try:
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as exc:  # noqa: BLE001 - Playwright raises its own Error type
                if any(marker in str(exc) for marker in _REFUSAL_BROWSER_ERRORS):
                    raise SourceBlocked(f"the site refused this network at {url} "
                                        f"({str(exc).splitlines()[0][:200]})") from None
                raise
            status = response.status if response is not None else 0
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
