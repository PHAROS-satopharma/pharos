"""PHAROS — how the three EMA list readers (EURD, herbal, literature monitoring) reach EMA's site.

Until 17 Nov 2026 each of them called ``httpx.get`` once, with its own User-Agent, no pause and no retry, so
one "429 Too Many Requests" from EMA lost the day's read. From 13 to 16 Nov EMA answered all three with 429
in most daily runs, while EMA's own feeds in the same runs (ema-dhpc, ema-psusa, ema-prac) were read through
``FetchContext`` without a failure. They now go through ``FetchContext`` too: one request at a time with a gap,
the same browser User-Agent, a 429 or 503 waited out (its Retry-After, else 30 s then 60 s) and tried twice
more. A list EMA still refuses after that raises, and the workflow step warns and keeps the stored list.

The originals are archived by the readers themselves (``Archive().put`` in their ``refresh``), so this context
archives nothing.
"""

from __future__ import annotations

import httpx

from collectors.core.archive import Archive
from collectors.core.context import FetchContext

# Excel and JSON originals: accept anything, as a browser does for a download link.
ANY = "*/*"


def ema_context(run_id: str, *, transport: httpx.BaseTransport | None = None) -> FetchContext:
    """A ``FetchContext`` for one EMA list read. Tests pass a ``MockTransport`` (then no DNS check runs)."""
    return FetchContext(None, run_id, archive=Archive(enabled=False), transport=transport,
                        public_only=transport is None)
