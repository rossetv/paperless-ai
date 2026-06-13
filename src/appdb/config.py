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
from collections.abc import Mapping

import structlog

from appdb.connection import transaction, utc_now_iso

log = structlog.get_logger(__name__)


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
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
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
    row = conn.execute("SELECT value FROM meta WHERE key = 'config_version'").fetchone()
    return int(row["value"]) if row is not None else 0


def snapshot_config_with_version(
    conn: sqlite3.Connection,
) -> tuple[int, dict[str, str]]:
    """Atomically read ``config_version`` and ``config`` rows in one snapshot.

    A hot-load reader needs the version *and* the data the version describes,
    consistently — otherwise a concurrent writer landing between the two reads
    can stamp the new version onto the old data (or the new data onto the old
    version) and the reader caches that mismatch indefinitely.

    The two reads are wrapped in one ``BEGIN DEFERRED`` transaction, which
    pins SQLite's WAL snapshot for the duration. ``BEGIN DEFERRED`` does not
    take the write lock; concurrent writers continue to commit, but this
    reader sees the snapshot it opened with for both statements. The commit
    closes the snapshot cleanly without taking any lock.

    Args:
        conn: An open, migrated ``app.db`` connection.

    Returns:
        ``(version, config_table)`` — the configuration version and the
        ``key → value`` mapping captured at the same point in time.
    """
    # rationale: SQLite's "deferred" mode is the snapshot-isolation knob a
    # read-only transaction needs (CODE_GUIDELINES §9). The connection's
    # autocommit default would otherwise issue each SELECT in its own
    # transaction, opening the race window the hot-load path closes here.
    conn.execute("BEGIN DEFERRED")
    try:
        version = get_config_version(conn)
        config_table = get_all(conn)
    finally:
        if conn.in_transaction:
            conn.commit()
    return version, config_table


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    """Insert or update one configuration key inside a ``BEGIN IMMEDIATE``.

    A thin single-key wrapper over :func:`set_many`, so the upsert SQL and the
    ``config_version`` bump live in exactly one place. Upserts on the ``key``
    primary key (an existing key is overwritten, not a conflict); ``updated_at``
    is stamped with the current UTC time; the bump shares the same
    ``BEGIN IMMEDIATE`` transaction as the write, so a hot-loading reader sees
    the new value and the new counter together, never one without the other.

    Args:
        conn: An open ``app.db`` connection.
        key: The configuration key.
        value: The raw string value to store.
    """
    set_many(conn, {key: value})


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
    with transaction(conn):
        set_many_in_transaction(conn, values)


def set_many_in_transaction(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Write *values* and bump ``config_version`` inside the caller's transaction.

    Callers that need a wider atomic boundary (e.g. the Settings PUT, which
    must validate against the same snapshot it writes against) open one
    ``BEGIN IMMEDIATE`` themselves and route the inner write through this
    function rather than :func:`set_many`. SQLite forbids nested
    ``BEGIN IMMEDIATE`` calls on one connection, so calling :func:`set_many`
    from inside an existing :func:`~appdb.connection.transaction` would raise
    "cannot start a transaction within a transaction".

    The caller is responsible for the surrounding ``BEGIN IMMEDIATE`` — this
    function takes no lock and emits no commit; it only stages the writes
    and the version bump on the connection's active transaction. An empty
    *values* mapping is a no-op (no write, no bump).

    Args:
        conn: An open ``app.db`` connection currently inside a
            ``BEGIN IMMEDIATE`` transaction the caller manages.
        values: A mapping of configuration key to raw string value.
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

    First-run import (web-redesign spec §5): when a deployment that was
    configured with environment variables is upgraded to config-in-database,
    the ``config`` table is empty. This function copies every catalogue key
    that is actually set in *environ* into the table, so the deployment keeps
    its existing configuration without the admin re-entering it.

    It seeds **only when the table is empty**. On a database that already has
    any configuration row it is a no-op and returns 0 — so it can never
    overwrite a value an administrator has since edited through the Settings
    screen. The check and the writes are not wrapped in one transaction
    because seeding runs once at startup before the server accepts requests;
    no concurrent writer exists.

    Args:
        conn: An open, migrated ``app.db`` connection.
        environ: The environment mapping to seed from — normally
            ``os.environ``; tests pass a plain dict.
        keys: The set of canonical configuration keys to consider. Keys in
            *environ* that are not in this set (``PATH``, ``HOME``, the
            bootstrap variables) are ignored.

    Returns:
        The number of keys seeded — 0 when the table was already populated or
        when no catalogue key was present in *environ*.
    """
    already_populated = conn.execute("SELECT 1 FROM config LIMIT 1").fetchone()
    if already_populated is not None:
        return 0

    to_seed = {key: environ[key] for key in keys if key in environ}
    set_many(conn, to_seed)
    if to_seed:
        log.info("appdb.config_seeded_from_env", key_count=len(to_seed))
    return len(to_seed)
