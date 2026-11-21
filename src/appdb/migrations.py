"""Forward-only migration runner for ``app.db``.

Each migration and its ``schema_version`` bump run in one transaction. The
machinery is copied from ``store.migrations`` rather than shared so the two
databases version independently. Add a new :data:`MIGRATIONS` entry; never edit
an existing one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import structlog

from appdb.connection import utc_now_iso

log = structlog.get_logger(__name__)

# Tells "fresh database" apart from a broken one (malformed image, locked
# file), whose different OperationalError must never be masked as fresh.
_NO_SUCH_TABLE_MARKER = "no such table"


def _is_missing_table_error(exc: sqlite3.Error) -> bool:
    """Return whether *exc* is a SQLite "no such table" operational error."""
    return (
        isinstance(exc, sqlite3.OperationalError)
        and _NO_SUCH_TABLE_MARKER in str(exc).lower()
    )


class AppDbError(Exception):
    """Base exception for application-database failures.

    Notably raised for a ``schema_version`` newer than any known migration.
    """


def _apply_schema_string(conn: sqlite3.Connection, schema: str) -> None:
    """Execute each ``CREATE``/``INSERT`` statement in *schema* on *conn*.

    ``conn.executescript`` is avoided because its implicit ``COMMIT`` would
    break the surrounding transaction and could leave the schema applied but
    ``schema_version`` un-advanced. ``--`` comment lines are stripped before
    splitting on ``";"`` because a ``;`` inside a comment would break a
    statement. Keep in step with ``store.migrations._migrate_v1``.
    """
    comment_stripped = "\n".join(
        line for line in schema.splitlines() if not line.strip().startswith("--")
    )
    for statement in comment_stripped.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Apply the v1 schema: the users and sessions tables and their indexes."""
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V1  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V1)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Apply the v2 schema: the recent_searches table and its index."""
    from appdb.schema import SCHEMA_V2  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V2)


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Apply the v3 schema: the api_keys table and its two indexes."""
    from appdb.schema import SCHEMA_V3  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V3)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Apply the v4 schema: the config table, and seed ``config_version`` at 0."""
    from appdb.schema import SCHEMA_V4  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V4)
    # OR IGNORE: never clobber a counter a running deployment has bumped.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('config_version', '0')"
    )


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Apply the v5 schema: the daemon_status and reconcile_activity tables."""
    from appdb.schema import SCHEMA_V5  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V5)


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Migrate AI_MODELS to OCR_MODELS and CLASSIFY_MODELS (config split).

    The ``AI_MODELS`` value is copied to whichever of the two keys is absent,
    then deleted, and ``config_version`` is bumped so running processes reload.
    """
    row = conn.execute("SELECT value FROM config WHERE key = 'AI_MODELS'").fetchone()
    if row is None:
        return

    legacy_value: str = row["value"]
    now = utc_now_iso()

    # Never overwrite a key an operator has already set explicitly.
    for key in ("OCR_MODELS", "CLASSIFY_MODELS"):
        existing = conn.execute("SELECT 1 FROM config WHERE key = ?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, legacy_value, now),
            )

    conn.execute("DELETE FROM config WHERE key = 'AI_MODELS'")

    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'config_version'"
    )

    log.info("appdb.migration_v6_ai_models_split")


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Apply the v7 schema: the api_key_usage table (per-key daily spend quota)."""
    from appdb.schema import SCHEMA_V7  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V7)


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """Apply the v8 schema: the model_pricing table (cached model-price book).

    Created empty; the price book seeds itself from
    :data:`search.pricing.MODEL_PRICES` when the cache is empty.
    """
    from appdb.schema import SCHEMA_V8  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V8)


# (schema_version, migration) pairs in strictly ascending order; the runner
# relies on it.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
    (8, _migrate_v8),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply every pending migration to *conn* and advance ``schema_version``.

    Each migration runs in its own transaction together with its version bump.

    Raises:
        AppDbError: The stored ``schema_version`` is newer than any known
            migration, so the database was written by a newer release.
    """
    current_version = _read_schema_version(conn)
    max_known_version = MIGRATIONS[-1][0]

    if current_version > max_known_version:
        raise AppDbError(
            f"app.db schema_version {current_version} is higher than the "
            f"maximum known migration version {max_known_version}. This "
            "database was written by a newer version of the application. "
            "Upgrade the application before using this database."
        )

    pending = [(v, fn) for v, fn in MIGRATIONS if v > current_version]

    for version, migration_fn in pending:
        log.info(
            "appdb.migration_applied",
            version=version,
            previous_version=current_version,
        )
        # An explicit BEGIN is required for atomicity: under the sqlite3
        # module's legacy transaction handling a DDL statement triggers no
        # implicit BEGIN, so without this each CREATE would autocommit and a
        # mid-migration failure would leave the schema half-applied.
        conn.execute("BEGIN")
        try:
            migration_fn(conn)
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
    """Return the stored ``schema_version``, or 0 for a fresh database.

    Any other OperationalError (malformed image, locked file) propagates, so a
    corrupt or busy ``app.db`` fails loud instead of being re-migrated.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc):
            return 0
        # A malformed or locked database must fail loud, never be re-migrated.
        raise
    return int(row[0]) if row is not None else 0
