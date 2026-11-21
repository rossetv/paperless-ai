"""Versioned migration runner for the search index, and the store's exceptions.

Each migration runs in its own transaction, which also advances
``meta.schema_version``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import structlog

log = structlog.get_logger(__name__)

# Substring SQLite puts in the OperationalError message when a queried table
# does not exist. Used to tell "fresh database, no schema yet" apart from a
# genuinely broken database (a malformed disk image, a locked file), which
# raises a *different* OperationalError that must never be masked as fresh.
_NO_SUCH_TABLE_MARKER = "no such table"


def _is_missing_table_error(exc: sqlite3.Error) -> bool:
    """Return whether *exc* is a SQLite "no such table" operational error."""
    return (
        isinstance(exc, sqlite3.OperationalError)
        and _NO_SUCH_TABLE_MARKER in str(exc).lower()
    )


class StoreError(Exception):
    """Base exception for all store-layer failures."""


class SchemaNotReadyError(StoreError):
    """The index database exists but its schema has not been created yet.

    ``sqlite3.connect`` creates an empty file on open, so an existing file does
    not mean the indexer has run ``ensure_schema``. This lets callers such as
    ``/api/healthz`` tell "not built yet" from corruption.
    """


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Apply the v1 schema: all tables, virtual tables, and indexes."""
    # Local import: schema.py imports run_migrations from this module.
    from store.schema import _SCHEMA  # noqa: PLC0415

    # Not executescript(): it issues an implicit COMMIT, which would break the
    # transaction run_migrations() opened. Comments are stripped before splitting
    # because a ";" inside a "--" line would produce a broken fragment.
    comment_stripped = "\n".join(
        line for line in _SCHEMA.splitlines() if not line.strip().startswith("--")
    )
    for statement in comment_stripped.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Add idx_documents_indexed_at for the Library's default "added" sort.

    Without it SQLite sorts the whole documents table on every page. On a fresh
    database _migrate_v1 already created it, so ``IF NOT EXISTS`` makes this a no-op.
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_indexed_at ON documents (indexed_at)"
    )


# (version, migration) pairs in strictly ascending order; the version is the
# schema_version written once the migration commits.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to *conn* and advance schema_version.

    Raises:
        StoreError: The stored schema_version is newer than any known migration,
            i.e. the database was written by a newer version of the code.
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
        # Explicit BEGIN: under sqlite3's legacy transaction handling DDL opens
        # no implicit transaction, so each statement would autocommit and a
        # failure would leave the schema half-applied.
        conn.execute("BEGIN")
        try:
            migration_fn(conn)
            # Same transaction, so a crash rolls back the version with the DDL.
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(version),),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        current_version = version


def _read_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema_version from meta, or 0 for a fresh database."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc):
            return 0
        # A corrupt or locked database must not be masked as version 0, which
        # would re-run every migration against it.
        raise
    return int(row[0]) if row is not None else 0
