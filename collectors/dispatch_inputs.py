"""PHAROS — read a hand-run workflow's inputs from the event file, so they never reach the run log.

The repository is public, and so are its run logs. A step's ``env:`` is printed at the head of its log, so an
input passed as ``EMAIL: ${{ inputs.email }}`` is printed with it. The message workflows run
``--from-event "$GITHUB_EVENT_PATH"`` instead and read what was typed from that file, which is never printed.
"""

from __future__ import annotations

import json


def read(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return (json.load(fh) or {}).get("inputs") or {}


def ticked(value) -> bool:
    """A boolean input arrives as true/false in the event file, or as the string "true"/"false"."""
    return value is True or str(value).strip().lower() == "true"
