"""Thin psycopg 3 wrapper: dict rows, autocommit by default, explicit transactions.

Connects with ``SUPABASE_DB_URL`` (service role, direct Postgres). Prepared statements are
disabled so the same code works through Supabase's transaction pooler.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator


def _dumps(value: Any) -> str:
    # Postgres jsonb refuses the escaped NUL character, which a scraped page can carry.
    return json.dumps(value, ensure_ascii=False, default=str).replace("\\u0000", "")


def jsonb(value: Any) -> Any:
    """Wrap a Python value for a jsonb parameter."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - only without psycopg (fixture tests)
        return _dumps(value)
    return Jsonb(value, dumps=_dumps)


def clean(params: Any) -> Any:
    """Drop NUL characters from every text parameter: Postgres refuses them in text columns, and one
    notice carrying one must never fail its whole source."""
    if isinstance(params, str):
        return params.replace("\x00", "")
    if isinstance(params, dict):
        return {k: clean(v) for k, v in params.items()}
    if isinstance(params, (list, tuple)):
        return type(params)(clean(v) for v in params)
    return params


class Db:
    def __init__(self, dsn: str | None = None) -> None:
        import psycopg
        from psycopg.rows import dict_row

        dsn = dsn or os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            raise RuntimeError("SUPABASE_DB_URL is not set")
        self.conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row,
                                    prepare_threshold=None, connect_timeout=20,
                                    application_name="sato-safety-watch-collectors")
        self._depth = 0

    def fetchall(self, sql: str, params: dict | tuple | None = None) -> list[dict]:
        with self.conn.cursor() as cur:
            cur.execute(sql, clean(params))
            return list(cur.fetchall()) if cur.description else []

    def fetchone(self, sql: str, params: dict | tuple | None = None) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, clean(params))
            return cur.fetchone() if cur.description else None

    def execute(self, sql: str, params: dict | tuple | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, clean(params))

    @contextmanager
    def transaction(self) -> Iterator["Db"]:
        """Nestable: inner blocks become savepoints."""
        with self.conn.transaction():
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1

    def close(self) -> None:
        self.conn.close()
