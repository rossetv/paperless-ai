"""The ``config`` table: a key/value store of raw env-var strings.

Keys are canonical env-var names; parsing and validation belong to
:mod:`common.config`. Every write bumps ``meta.config_version`` in the same
transaction, which is how processes detect a config change without a restart.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

import structlog

from appdb.connection import transaction, utc_now_iso

log = structlog.get_logger(__name__)


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    """Return every configuration key/value pair as a plain dict."""
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the value for *key*, or ``None`` when the key is not set."""
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else None


def _bump_config_version(conn: sqlite3.Connection) -> None:
    """Increment the ``config_version`` counter in the ``meta`` table.

    Must run inside the write's transaction so the bump commits or rolls back
    with it. The ``+ 1`` is computed in SQL so serialised writers cannot lose a
    bump.
    """
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'config_version'"
    )


def get_config_version(conn: sqlite3.Connection) -> int:
    """Return the current ``config_version``, the hot-load change counter.

    Processes re-read it at a safe boundary and rebuild their
    :class:`~common.config.Settings` only when it has moved.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'config_version'").fetchone()
    return int(row["value"]) if row is not None else 0


def snapshot_config_with_version(
    conn: sqlite3.Connection,
) -> tuple[int, dict[str, str]]:
    """Atomically read ``config_version`` and ``config`` rows in one snapshot.

    Without one snapshot, a writer landing between the two reads could pair the
    new version with the old data, and the reader would cache that mismatch
    indefinitely. ``BEGIN DEFERRED`` pins the WAL snapshot without taking the
    write lock.
    """
    conn.execute("BEGIN DEFERRED")
    try:
        version = get_config_version(conn)
        config_table = get_all(conn)
    finally:
        if conn.in_transaction:
            conn.commit()
    return version, config_table


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update one configuration key; see :func:`set_many`."""
    set_many(conn, {key: value})


def set_many(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Insert or update a batch of configuration keys atomically.

    One ``BEGIN IMMEDIATE`` transaction and one ``config_version`` bump for the
    whole batch. An empty *values* is a no-op that takes no lock.
    """
    if not values:
        return
    with transaction(conn):
        set_many_in_transaction(conn, values)


def set_many_in_transaction(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Write *values* and bump ``config_version`` inside the caller's transaction.

    For callers that need a wider atomic boundary (e.g. the Settings PUT, which
    validates against the snapshot it writes): SQLite cannot nest
    ``BEGIN IMMEDIATE``, so :func:`set_many` cannot be called from inside a
    :func:`~appdb.connection.transaction`. Takes no lock and does not commit.
    """
    if not values:
        return
    now = utc_now_iso()
    conn.executemany(
        "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        [(key, value, now) for key, value in values.items()],
    )
    _bump_config_version(conn)
    log.info("appdb.config_set_many", key_count=len(values))


def seed_from_env(
    conn: sqlite3.Connection,
    *,
    environ: Mapping[str, str],
    keys: set[str],
) -> int:
    """Populate an empty ``config`` table from the process environment.

    Copies every key in *keys* that is set in *environ*, so an env-configured
    deployment keeps its settings on first run. Seeds only when the table is
    empty, so it never overwrites an edit made in the Settings screen. The check
    and write need no shared transaction: seeding runs once at startup, before
    any concurrent writer exists. Returns the number of keys seeded.
    """
    already_populated = conn.execute("SELECT 1 FROM config LIMIT 1").fetchone()
    if already_populated is not None:
        return 0

    to_seed = {key: environ[key] for key in keys if key in environ}
    set_many(conn, to_seed)
    if to_seed:
        log.info("appdb.config_seeded_from_env", key_count=len(to_seed))
    return len(to_seed)
