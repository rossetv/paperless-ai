"""Application configuration in the application database — the ``config`` table.

This module owns the typed query functions over the ``config`` table. The
table is a flat key/value store: every key is the canonical
environment-variable name (``OPENAI_API_KEY``, ``CHUNK_SIZE``, …) and every
value is the raw string form that env-var would have carried.

Parsing, typing, validation and defaults are **not** done here — that is
:mod:`common.config`'s job. ``appdb.config`` keeps ``app.db`` a dumb store:
strings in, strings out. This separation is what lets the four daemons read
the table without importing the validation logic.

**Hot-load counter.** Every write bumps the ``config_version`` row in the
``meta`` table, in the same ``BEGIN IMMEDIATE`` transaction as the write.
``get_config_version`` reads it. This monotonically-increasing integer is
how every process detects a config change without a restart: it re-reads
``config_version`` at a safe boundary and rebuilds its
:class:`~common.config.Settings` only when the number moved (web-redesign §5,
Wave 4). The ``config_version`` row is seeded at ``0`` by migration v4.

Because :func:`set_value` and :func:`set_many` write inside the shared
:func:`appdb.connection.transaction` (``BEGIN IMMEDIATE``) context manager,
two concurrent writers serialise on SQLite's write lock — neither the row
nor the version bump can be lost, and a reader sees the new value and the
new ``config_version`` together or sees neither.

Higher layers (the search server's Settings endpoints, and ``common.config``
at every process's startup and re-check) call these functions; nobody else
writes ``config``-table SQL.

Allowed deps: sqlite3, structlog, :mod:`appdb.connection`. Forbidden: store,
search, daemon packages, FastAPI, common (this module is below common in the
import graph — common imports it, not the reverse).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import structlog

from appdb.connection import transaction

log = structlog.get_logger(__name__)


def _utc_now_iso() -> str:
    """Return the current UTC time as an offset-aware ISO-8601 string —
    the timestamp format every ``app.db`` table stores."""
    return datetime.now(timezone.utc).isoformat()


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    """Return every configuration key/value pair as a plain dict.

    Args:
        conn: An open, migrated ``app.db`` connection.

    Returns:
        A mapping of every ``config`` key to its string value. Empty when no
        configuration has been written yet (a fresh database, pre-seeding).
    """
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the value for *key*, or ``None`` when the key is not set.

    Args:
        conn: An open ``app.db`` connection.
        key: The configuration key (a canonical env-var name).
    """
    row = conn.execute(
        "SELECT value FROM config WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row is not None else None


def _bump_config_version(conn: sqlite3.Connection) -> None:
    """Increment the ``config_version`` counter in the ``meta`` table.

    Called by every write **inside that write's transaction**, so the bump
    commits or rolls back atomically with the configuration change. The row
    is seeded at ``0`` by migration v4; the ``+ 1`` is computed in SQL so two
    writers serialised by SQLite's write lock cannot lose a bump.
    """
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'config_version'"
    )


def get_config_version(conn: sqlite3.Connection) -> int:
    """Return the current ``config_version`` — the hot-load change counter.

    Every process re-reads this cheap single-row integer at a safe boundary
    (a daemon between documents, the search server per request) and rebuilds
    its :class:`~common.config.Settings` only when the number has moved since
    the last check. A migrated database that has never been written reports
    ``0``.

    Args:
        conn: An open, migrated ``app.db`` connection.

    Returns:
        The monotonically-increasing configuration version.
    """
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'config_version'"
    ).fetchone()
    return int(row["value"]) if row is not None else 0


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update one configuration key inside a ``BEGIN IMMEDIATE``.

    Upserts on the ``key`` primary key, so calling it for an existing key
    overwrites the value rather than failing. ``updated_at`` is stamped with
    the current UTC time. The ``config_version`` counter is bumped in the
    **same** ``BEGIN IMMEDIATE`` transaction so a hot-loading reader sees the
    new value and the new counter together, never one without the other; two
    concurrent writers serialise on SQLite's write lock so neither bump is
    lost.

    Args:
        conn: An open ``app.db`` connection.
        key: The configuration key.
        value: The raw string value to store.
    """
    with transaction(conn):
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, _utc_now_iso()),
        )
        _bump_config_version(conn)
    log.info("appdb.config_set", key=key)


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Insert or update a batch of configuration keys atomically.

    Every pair is written inside one ``BEGIN IMMEDIATE`` transaction, so a
    failure part-way through rolls the whole batch back — the ``config``
    table is never left half-updated. The ``config_version`` counter is
    bumped **once** for the whole batch, in that same transaction (a batch
    save is one configuration change). An empty *values* mapping is a no-op:
    it writes nothing, takes no lock, and bumps nothing.

    Args:
        conn: An open ``app.db`` connection.
        values: A mapping of configuration key to raw string value.
    """
    if not values:
        return
    now = _utc_now_iso()
    with transaction(conn):
        conn.executemany(
            "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            [(key, value, now) for key, value in values.items()],
        )
        _bump_config_version(conn)
    log.info("appdb.config_set_many", key_count=len(values))
