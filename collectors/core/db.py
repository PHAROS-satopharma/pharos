"""Thin psycopg 3 wrapper: dict rows, autocommit by default, explicit transactions.

Connects with ``SUPABASE_DB_URL`` (service role, direct Postgres). Prepared statements are
disabled so the same code works through Supabase's transaction pooler.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator


def jsonb(value: Any) -> Any:
    """Wrap a Python value for a jsonb parameter."""
    try:
        from psycopg.types.json import Jsonb
    except ImportError:  # pragma: no cover - only without psycopg (fixture tests)
        return json.dumps(value, ensure_ascii=False, default=str)
    return Jsonb(value, dumps=lambda v: json.dumps(v, ensure_ascii=False, default=str))


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
            cur.execute(sql, params)
            return list(cur.fetchall()) if cur.description else []

    def fetchone(self, sql: str, params: dict | tuple | None = None) -> dict | None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if cur.description else None

    def execute(self, sql: str, params: dict | tuple | None = None) -> None:
        with self.conn.cursor() as cur:
            cur.execute(sql, params)

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
