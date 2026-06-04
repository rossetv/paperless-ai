"""Versioned migration runner for the search index store.

Owns the ordered list of migration functions and the logic that applies
pending migrations to a SQLite connection on startup.  Each migration runs
inside its own transaction; the schema_version in meta is advanced after
each one commits.

This module also defines StoreError — the store package's base exception type.
All other store modules raise StoreError (or a subclass) for domain failures.

Allowed deps: sqlite3, store.schema (for _SCHEMA), structlog.
Forbidden: imports from any package above store/ in the layer hierarchy.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import structlog

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain exception
# ---------------------------------------------------------------------------


class StoreError(Exception):
    """Base exception for all store-layer failures.

    Raised when the store encounters a condition it cannot handle safely —
    such as an unknown future schema version — that the caller must address.
    Callers that need to distinguish specific failures subclass this type.
    """


class SchemaNotReadyError(StoreError):
    """The index database exists but its schema has not been created yet.

    ``sqlite3.connect`` auto-creates an empty database file the moment a path
    is opened, so a present-but-empty file does **not** mean the index is
    ready: the indexer may not yet have run ``ensure_schema``.  A read against
    such a database fails with ``no such table``.  The store raises this typed
    subclass for that case so callers — notably the search server's
    ``/api/healthz`` handler — can distinguish "indexer has not built the
    index yet" from genuine corruption without inspecting ``sqlite3`` internals
    (``CODE_GUIDELINES.md`` §8.2/§9.1).
    """


# ---------------------------------------------------------------------------
# Migration functions (private)
# ---------------------------------------------------------------------------


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Apply the v1 schema: all tables, virtual tables, and indexes.

    Runs each DDL statement from _SCHEMA individually via conn.execute() so
    that all DDL and the schema_version write in run_migrations() stay inside
    the single explicit transaction that run_migrations() opens.
    conn.executescript() issues an implicit COMMIT before executing, which
    would break atomicity and allow a crash to leave the schema applied but
    schema_version un-advanced.

    Every statement uses IF NOT EXISTS so re-running is harmless, though the
    migration runner only calls this when the stored schema_version is 0.

    The import is deferred to the function body to break the mutual import
    cycle: schema.py imports run_migrations from this module, and this
    function needs _SCHEMA from schema.py.  A module-level import would cause
    a circular ImportError; a local import resolves after both modules are
    initialised.
    """
    # Local import to break the schema ↔ migrations circular dependency.
    from store.schema import _SCHEMA  # noqa: PLC0415

    # executescript() is deliberately avoided: it issues an implicit COMMIT
    # before executing, breaking the atomicity of the surrounding transaction.
    # Stripping comments first, then splitting on ";", and calling execute()
    # for each non-empty statement keeps all DDL and the schema_version write
    # in one atomic transaction.
    #
    # Comments must be stripped before splitting: a ";" inside a comment line
    # (e.g. "-- …; the writer keeps…") would otherwise produce a broken fragment
    # starting with plain text rather than a SQL keyword.
    comment_stripped = "\n".join(
        line for line in _SCHEMA.splitlines() if not line.strip().startswith("--")
    )
    for statement in comment_stripped.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add idx_documents_indexed_at for the Library's default "added" sort.

    The browse view's default sort is ``ORDER BY indexed_at DESC, id DESC``;
    without an index on ``indexed_at`` SQLite sorts the whole documents table on
    every page request. ``IF NOT EXISTS`` makes this a no-op on a fresh database
    (where _migrate_v1 already created the index from the current _SCHEMA), so
    only databases created before v2 actually build it here.
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_indexed_at "
        "ON documents (indexed_at)"
    )


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------

# Ordered list of (version, migration_function) pairs.  The version is the
# schema_version value written to meta *after* the migration commits.  Entries
# must be in strictly ascending version order; the runner relies on this.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to *conn* and advance schema_version.

    Reads meta.schema_version (treated as 0 when the meta table or its row
    does not exist — a fresh database has neither).  Applies every migration
    whose version is higher than the current version, in ascending order,
    each inside its own ``with conn:`` transaction.  After each migration the
    new schema_version is persisted in meta.

    Raises StoreError when the stored schema_version is higher than the
    highest known migration version.  This indicates a database written by a
    newer code version; silently proceeding could corrupt or misinterpret the
    schema.

    Args:
        conn: An open connection returned by store.schema.connect().

    Raises:
        StoreError: The database's schema_version exceeds the maximum known
            migration version.
    """
    current_version = _read_schema_version(conn)
    max_known_version = MIGRATIONS[-1][0]

    if current_version > max_known_version:
        raise StoreError(
            f"Database schema_version {current_version} is higher than the "
            f"maximum known migration version {max_known_version}. "
            "This database was written by a newer version of the code. "
            "Upgrade the application before using this database."
        )

    pending = [(v, fn) for v, fn in MIGRATIONS if v > current_version]

    for version, migration_fn in pending:
        log.info(
            "store.migration_applied",
            version=version,
            previous_version=current_version,
        )
        # An explicit BEGIN is required for atomicity. Under the sqlite3
        # module's legacy transaction handling a DDL statement (CREATE TABLE /
        # INDEX) triggers no implicit BEGIN, and a bare ``with conn:`` opens no
        # transaction either — so without this each DDL statement would
        # autocommit and a mid-migration failure would leave the schema
        # half-applied. BEGIN makes the whole migration — every DDL statement
        # plus the schema_version write — one transaction committed or rolled
        # back as a unit.
        conn.execute("BEGIN")
        try:
            migration_fn(conn)
            # Persist the new version inside the same transaction so a crash
            # mid-migration rolls back to the pre-migration state entirely.
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        current_version = version


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _read_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema_version from meta, or 0 for a fresh database.

    Returns 0 when either the meta table does not exist (fresh database, no
    schema applied yet) or when the schema_version row is absent.

    Args:
        conn: An open SQLite connection.

    Returns:
        The stored schema_version as an integer, or 0 if absent.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        # meta table does not exist yet — this is a fresh database.
        return 0
    return int(row[0]) if row is not None else 0
