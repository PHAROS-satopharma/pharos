"""Words compared the way the database compares them (``coding_norm()``, migration 0061)."""

from __future__ import annotations

import re

_OTHER = re.compile(r"[^0-9a-z\u0080-\uffff]+")


def norm(text: str | None) -> str:
    """ASCII lower case; every run of characters other than ASCII letters, digits and non-ASCII letters is one
    space. Characters beyond ASCII are kept as written (the database lower-cases ASCII only)."""
    low = "".join(ch.lower() if ch < "\x80" else ch for ch in (text or ""))
    return _OTHER.sub(" ", low).strip()
