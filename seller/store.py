"""SQLite state for the stdout Network seller agent.

One file holds accounts, media buys, packages, creatives, assignments,
impressions and idempotency records. Good enough for a demo seller; swap for
Postgres if this ever has to survive contact with real money.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.environ.get("STDOUT_DB", os.path.join(os.path.dirname(__file__), "..", "stdout_network.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    brand_domain TEXT NOT NULL,
    operator TEXT NOT NULL,
    name TEXT,
    billing TEXT NOT NULL DEFAULT 'operator',
    sandbox INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE (brand_domain, operator, sandbox)
);
CREATE TABLE IF NOT EXISTS media_buys (
    media_buy_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    brand_domain TEXT NOT NULL,
    name TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    currency TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    creative_deadline TEXT NOT NULL,
    context_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS packages (
    package_id TEXT PRIMARY KEY,
    media_buy_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    pricing_option_id TEXT NOT NULL,
    format_option_id TEXT NOT NULL,
    budget REAL NOT NULL,
    cpm REAL NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    context_json TEXT,
    targeting_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creatives (
    account_id TEXT NOT NULL,
    creative_id TEXT NOT NULL,
    name TEXT NOT NULL,
    format_option_id TEXT NOT NULL,
    assets_json TEXT NOT NULL,
    status TEXT NOT NULL,
    review_notes TEXT,
    revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, creative_id)
);
CREATE TABLE IF NOT EXISTS assignments (
    package_id TEXT NOT NULL,
    creative_id TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 100,
    PRIMARY KEY (package_id, creative_id)
);
CREATE TABLE IF NOT EXISTS impressions (
    impression_id TEXT PRIMARY KEY,
    package_id TEXT NOT NULL,
    creative_id TEXT NOT NULL,
    moment TEXT NOT NULL,
    tool TEXT,
    country TEXT,
    served_at TEXT NOT NULL,
    rendered_at TEXT,
    clicked_at TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (
    idem_key TEXT NOT NULL,
    tool TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (idem_key, tool)
);
CREATE INDEX IF NOT EXISTS idx_imp_pkg ON impressions(package_id);
CREATE INDEX IF NOT EXISTS idx_pkg_mb ON packages(media_buy_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Store:
    def __init__(self, path: str = DB_PATH):
        self.path = os.path.abspath(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        # Additive migrations for databases created by earlier versions.
        for table, column in (("packages", "targeting_json TEXT"), ("impressions", "country TEXT")):
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass

    # -- low level ---------------------------------------------------------
    def q(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql: str, args: tuple = ()) -> None:
        with self._lock:
            self._conn.execute(sql, args)

    def tx(self):
        """Context manager for an atomic multi-statement write."""
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._lock.acquire()
                store._conn.execute("BEGIN IMMEDIATE")
                return store

            def __exit__(self_inner, exc_type, exc, tb):
                try:
                    store._conn.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store._lock.release()
                return False

        return _Tx()

    # -- idempotency -------------------------------------------------------
    def idem_get(self, key: str, tool: str) -> dict | None:
        return self.one("SELECT * FROM idempotency WHERE idem_key=? AND tool=?", (key, tool))

    def idem_put(self, key: str, tool: str, payload_hash: str, response: dict) -> None:
        self.x(
            "INSERT OR REPLACE INTO idempotency VALUES (?,?,?,?,?)",
            (key, tool, payload_hash, json.dumps(response), now_iso()),
        )

    def reset(self) -> None:
        with self._lock:
            for t in ("accounts", "media_buys", "packages", "creatives", "assignments", "impressions", "idempotency"):
                self._conn.execute(f"DELETE FROM {t}")
