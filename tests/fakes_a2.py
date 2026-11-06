"""PHAROS — test doubles for the A2 parser and SPC tests (no network, no database).

* ``FakeCtx`` answers ``get`` / ``browser_get`` from a URL → fixture-file map (anything else is
  a 404), and archives in memory (``archive`` / ``archiver.get``).
* ``source(id, url, **options)`` builds a ``SourceConfig`` without reading sources.yaml.
* ``SpcDb`` is a tiny in-memory stand-in for the SQL that ``collectors.spc.run`` issues.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path

from collectors.core.models import Fetched, SourceConfig

FIX = Path(__file__).resolve().parent / "fixtures"

_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
          ".pdf": "application/pdf", ".xml": "application/xml", ".txt": "text/plain"}


def fixture(rel: str) -> bytes:
    return (FIX / rel).read_bytes()


def fetched(rel: str, url: str = "https://example.invalid/", content_type: str | None = None):
    path = FIX / rel
    ctype = content_type or _TYPES.get(path.suffix, "application/octet-stream")
    return Fetched(200, url, path.read_bytes(), ctype)


def source(sid: str, url: str, *, languages: list[str] | None = None, parser: str = "",
           channel: str = "html", kind: str = "safety", **options) -> SourceConfig:
    return SourceConfig(id=sid, regulator_id="X", kind=kind, channel=channel, url=url,
                        parser=parser, languages=languages or ["en"], schedule="4h",
                        enabled=True, options=options, expected_max_gap_days=None)


class MemArchive:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, content: bytes, mime: str) -> tuple[str, str]:
        sha = hashlib.sha256(content).hexdigest()
        key = f"sha256/{sha[:2]}/{sha}"
        self.objects[key] = content
        return sha, key

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)


class FakeCtx:
    """``routes`` maps a URL (exact, or a prefix ending in ``*``) to a fixture path or bytes."""

    def __init__(self, routes: dict[str, str | bytes] | None = None, *, backfill: bool = False,
                 db=None) -> None:
        self.routes = dict(routes or {})
        self.backfill = backfill
        self.db = db
        self.dry_run = True
        self.archiver = MemArchive()
        self.requests: list[tuple[str, str, dict | None]] = []

    def _lookup(self, url: str):
        if url in self.routes:
            return self.routes[url]
        for k, v in self.routes.items():
            if k.endswith("*") and url.startswith(k[:-1]):
                return v
        return None

    def _answer(self, url: str) -> Fetched:
        hit = self._lookup(url)
        if hit is None:
            return Fetched(404, url, b"", "text/html")
        if isinstance(hit, bytes):
            return Fetched(200, url, hit, "text/html; charset=utf-8")
        f = fetched(hit, url)
        f.sha256, f.r2_key = self.archiver.put(f.content, f.mime)
        return f

    def get(self, url: str, *, accept: str | None = None, headers: dict | None = None,
            raise_for_status: bool = True, retry_server_errors: bool = True) -> Fetched:
        self.requests.append(("GET", url, headers))
        return self._answer(url)

    def forget(self, url: str) -> None:
        self.requests.append(("FORGET", url, None))

    def pace(self, host: str, seconds: float) -> None:
        self.requests.append(("PACE", host, {"seconds": seconds}))

    def browser_get(self, url: str, *, wait_selector: str | None = None,
                    timeout_ms: int = 45000) -> Fetched:
        self.requests.append(("BROWSER", url, {"wait_selector": wait_selector}))
        return self._answer(url)

    def archive(self, content: bytes, mime: str) -> tuple[str, str]:
        return self.archiver.put(content, mime)


class SpcDb:
    """Just enough of ``Db`` for ``collectors.spc.run.watch_product`` / ``record_change``."""

    def __init__(self) -> None:
        self.snapshots: list[dict] = []
        self.documents: list[dict] = []
        self.issues: list[dict] = []
        self.changes: list[dict] = []
        self.links: list[tuple] = []
        self.matches: list[dict] = []
        self.products: dict[tuple[str, str], dict] = {}
        self.our_labels: list[dict] = []        # current versions of our label: id, ingredient_id, lang, sections
        self.gaps: list[dict] = []              # label_gap rows the change writer stored

    @contextmanager
    def transaction(self):
        yield self

    @staticmethod
    def _sql(sql: str) -> str:
        return " ".join(sql.split()).lower()

    def fetchone(self, sql: str, params=None):
        q = self._sql(sql)
        p = dict(params or {})
        if q.startswith("insert into spc_product"):
            row = self.products.setdefault((p["src"], p["nid"]), {"id": str(uuid.uuid4())})
            row.update(ingredient_id=p["ing"], source_id=p["src"], country_code=p["cc"],
                       national_id=p["nid"], product_name=p["name"], mah=p["mah"], url=p["url"],
                       extra=_load(p["extra"]), active=True)
            return dict(row)
        if q.startswith("insert into spc_snapshot"):
            row = {"id": str(uuid.uuid4()), "spc_product_id": p["p"], "doc_date": p["d"],
                   "sha256": p["s"], "r2_key": p["k"], "section_hashes": _load(p["h"])}
            self.snapshots.append(row)
            return {"id": row["id"]}
        if q.startswith("select id, sha256, r2_key, section_hashes from spc_snapshot"):
            rows = [r for r in self.snapshots if r["spc_product_id"] == p["p"]]
            return dict(rows[-1]) if rows else None
        if q.startswith("insert into document"):
            if any(d["external_id"] == p["ext"] for d in self.documents):
                return None
            row = {"id": str(uuid.uuid4()), **p, "external_id": p["ext"], "structured": _load(p["st"])}
            self.documents.append(row)
            return {"id": row["id"]}
        if q.startswith("insert into issue ("):
            row = {"id": str(uuid.uuid4()), "title": p["t"], "anchor": p["d"], "first_date": p["f"]}
            self.issues.append(row)
            return {"id": row["id"]}
        if q.startswith("insert into spc_change"):
            assert "returning id" in q
            row = {"id": str(uuid.uuid4()), **p, "d": _load(p["d"])}
            self.changes.append(row)
            return {"id": row["id"]}
        raise AssertionError(f"unexpected fetchone: {q[:80]}")

    def fetchall(self, sql: str, params=None):
        q = self._sql(sql)
        p = dict(params or {})
        if q.startswith("select id, sha256, r2_key, section_hashes, doc_date from spc_snapshot"):
            rows = [dict(r) for r in self.snapshots if r["spc_product_id"] == p["p"]]
            return list(reversed(rows))[:p.get("n", len(rows))]
        if "from our_label" in q:
            assert "superseded_at is null" in q, "only the current version of our label is compared"
            return [{"id": r["id"], "lang": r["lang"], "sections": r["sections"]}
                    for r in self.our_labels if r["ingredient_id"] == p["i"]]
        raise AssertionError(f"unexpected fetchall: {self._sql(sql)[:80]}")

    def execute(self, sql: str, params=None) -> None:
        q = self._sql(sql)
        p = dict(params or {})
        if q.startswith("insert into label_gap"):
            assert "on conflict (spc_change_id, our_label_id) do update" in q
            self.gaps.append({**p, "gap": _load(p["g"])})
        elif q.startswith(("insert into issue_document", "insert into issue_ingredient")):
            self.links.append((q.split()[2], p))
        elif q.startswith("insert into match"):
            self.matches.append(p)
        elif q.startswith("update spc_product set checked_at = now()"):
            self.clock_n = getattr(self, "clock_n", 0) + 1     # an ever-later "now"
            for row in self.products.values():
                if row["id"] == p["p"]:
                    row["checked_at"] = self.clock_n
        elif q.startswith("update spc_product set active = false"):
            for (src, nid), row in self.products.items():
                if src == p["s"] and row["ingredient_id"] == p["i"] and nid not in p["k"]:
                    row["active"] = False
        else:
            raise AssertionError(f"unexpected execute: {q[:80]}")


def _load(value):
    """Undo ``jsonb()`` (psycopg Jsonb wrapper) or a JSON string."""
    inner = getattr(value, "obj", value)
    if isinstance(inner, str):
        try:
            return json.loads(inner)
        except ValueError:
            return inner
    return inner
