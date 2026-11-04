"""Parser loading by name, and the sources.yaml catalogue (load + sync into regulator/source)."""

from __future__ import annotations

import importlib
import json
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from collectors.core.models import (SOURCE_CHANNELS, SOURCE_KINDS, SOURCE_SCHEDULES,
                                    SourceConfig)

CATALOGUE = Path(__file__).resolve().parent.parent / "sources.yaml"


class CatalogueError(ValueError):
    pass


def load_parser(name: str) -> ModuleType:
    """``collectors.parsers.<name>`` — adding a parser never edits a shared file."""
    if not name.replace("_", "").isalnum():
        raise CatalogueError(f"bad parser name {name!r}")
    module = importlib.import_module(f"collectors.parsers.{name}")
    if not callable(getattr(module, "list_items", None)):
        raise CatalogueError(f"collectors.parsers.{name} has no list_items()")
    return module


def load_spc(name: str) -> ModuleType:
    return importlib.import_module(f"collectors.spc.{name}")


@lru_cache(maxsize=4)
def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_catalogue(path: str | Path = CATALOGUE) -> tuple[list[dict], list[SourceConfig], dict]:
    """-> (regulators, sources, notes by source id). Validates every enum value."""
    data = _read(str(path))
    regulators = data.get("regulators") or []
    reg_ids = {r["id"] for r in regulators}
    sources: list[SourceConfig] = []
    notes: dict[str, str | None] = {}
    seen: set[str] = set()
    for raw in data.get("sources") or []:
        sid = raw["id"]
        if sid in seen:
            raise CatalogueError(f"duplicate source id {sid}")
        seen.add(sid)
        if raw["regulator"] not in reg_ids:
            raise CatalogueError(f"{sid}: unknown regulator {raw['regulator']}")
        for key, allowed in (("kind", SOURCE_KINDS), ("channel", SOURCE_CHANNELS),
                             ("schedule", SOURCE_SCHEDULES)):
            if raw[key] not in allowed:
                raise CatalogueError(f"{sid}: bad {key} {raw[key]!r}")
        sources.append(SourceConfig(
            id=sid, regulator_id=raw["regulator"], kind=raw["kind"], channel=raw["channel"],
            url=raw["url"], parser=raw["parser"], languages=list(raw["languages"]),
            schedule=raw["schedule"], enabled=bool(raw.get("enabled", True)),
            options=dict(raw.get("options") or {}),
            expected_max_gap_days=raw.get("expected_max_gap_days"),
        ))
        notes[sid] = raw.get("notes")
    return regulators, sources, notes


def sync_catalogue(store: Any, path: str | Path = CATALOGUE) -> int:
    """Upsert every regulator and origin='catalogue' source. Never touches origin='user' rows."""
    regulators, sources, notes = load_catalogue(path)
    with store.transaction():
        for reg in regulators:
            store.upsert_regulator({
                "id": reg["id"], "country_code": reg["country_code"],
                "country_name": reg["country_name"], "name": reg["name"],
                "languages": list(reg["languages"]), "homepage": reg.get("homepage")})
        for src in sources:
            store.upsert_catalogue_source(src, notes.get(src.id))
    return len(sources)


def _options_from_notes(notes: str | None) -> dict:
    """A user-added source has no options column; a JSON object in ``notes`` is read as options."""
    if notes and notes.lstrip().startswith("{"):
        try:
            value = json.loads(notes)
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}
    return {}


def source_configs(store: Any, path: str | Path = CATALOGUE) -> list[SourceConfig]:
    """Every source row in the database as a SourceConfig, with options from the catalogue."""
    _, catalogue, _ = load_catalogue(path)
    options = {s.id: s.options for s in catalogue}
    out = []
    for row in store.list_sources():
        opts = options.get(row["id"]) if row.get("origin", "catalogue") == "catalogue" else None
        out.append(SourceConfig(
            id=row["id"], regulator_id=row["regulator_id"], kind=str(row["kind"]),
            channel=str(row["channel"]), url=row["url"], parser=row["parser"],
            languages=list(row["languages"] or []), schedule=str(row["schedule"]),
            enabled=bool(row["enabled"]),
            options=dict(opts if opts is not None else _options_from_notes(row.get("notes"))),
            expected_max_gap_days=row.get("expected_max_gap_days"),
        ))
    return out
