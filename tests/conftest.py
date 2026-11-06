"""PHAROS tests — shared set-up."""

from __future__ import annotations

import pytest

from collectors.parsers import base


@pytest.fixture(autouse=True)
def _no_watchlist_left_over():
    """A Runner sets the parsers' watched-name check for the whole process; no test inherits another's."""
    yield
    base.WATCHED = None
    base.DROPPED.clear()
