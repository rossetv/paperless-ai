"""Forward-only versioned migration runner for the application database.

Owns the ordered :data:`MIGRATIONS` list and the logic that applies pending
migrations to an ``app.db`` connection on startup. Each migration runs inside
its own explicit ``BEGIN…COMMIT`` transaction; the ``schema_version`` in the
``meta`` table is advanced inside that same transaction, so a crash mid-way
rolls the whole step back.

This is adapted from ``store.migrations`` — appdb deliberately does not share
code with ``store`` (see the package docstring), so the machinery is copied
and the exception type renamed to :class:`AppDbError`. Migrations are
forward-only: ``app.db`` starts empty, so there is never data to migrate
down; a new schema version is a new :data:`MIGRATIONS` entry, never an edit
to an existing one.

Allowed deps: sqlite3, structlog, appdb.schema (deferred import in the
migration body to break the schema ↔ migrations import cycle). Forbidden:
store, search, daemon packages.
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


class AppDbError(Exception):
    """Base exception for application-database failures.

    Raised when ``appdb`` meets a condition it cannot handle safely — most
    notably a ``schema_version`` higher than any migration the running code
    knows, which means the database was written by a newer release. Callers
    that must distinguish specific failures subclass this type.
    """


def _apply_schema_string(conn: sqlite3.Connection, schema: str) -> None:
    """Execute each ``CREATE``/``INSERT`` statement in *schema* on *conn*.

    Splits *schema* on ``";"`` and executes every non-empty statement via
    ``conn.execute``. ``conn.executescript`` is deliberately avoided — it
    issues an implicit ``COMMIT`` before running, which would break the
    atomicity of the surrounding transaction and could leave the schema applied
    but ``schema_version`` un-advanced.

    This is a package-private helper called only by the ``_migrate_vN``
    functions; it carries no deferred import because the callers do those.

    Args:
        conn: An open connection with an active transaction.
        schema: A ``;``-separated string of SQL DDL/DML statements.
    """
    for statement in schema.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(stmt)


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Apply the v1 schema: the users and sessions tables and their indexes.

    Executes each DDL statement from :data:`appdb.schema.SCHEMA_V1`
    individually via ``conn.execute`` so every statement stays inside the
    single explicit transaction :func:`run_migrations` opens.
    ``conn.executescript`` is deliberately avoided — it issues an implicit
    ``COMMIT`` before running, which would break the atomicity of the
    surrounding transaction and could leave the schema applied but
    ``schema_version`` un-advanced.

    The import of ``SCHEMA_V1`` is deferred to this function body to break
    the import cycle: ``appdb.schema`` imports :func:`run_migrations` from
    this module, and this function needs ``SCHEMA_V1`` from ``appdb.schema``.
    """
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V1  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V1)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """Apply the v2 schema: the recent_searches table and its index.

    Executes each DDL statement from :data:`appdb.schema.SCHEMA_V2`
    individually so every statement stays inside the single explicit
    transaction :func:`run_migrations` opens — ``conn.executescript`` is
    avoided for the same reason as in :func:`_migrate_v1` (it issues an
    implicit ``COMMIT`` that would break the migration's atomicity).

    The import of ``SCHEMA_V2`` is deferred to this function body to break
    the ``appdb.schema`` <-> ``appdb.migrations`` import cycle, exactly as
    :func:`_migrate_v1` defers ``SCHEMA_V1``.
    """
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V2  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V2)


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Apply the v3 schema: the api_keys table and its two indexes.

    Executes each DDL statement from :data:`appdb.schema.SCHEMA_V3`
    individually via ``conn.execute`` so every statement stays inside the
    single explicit transaction :func:`run_migrations` opens.
    ``conn.executescript`` is deliberately avoided — it issues an implicit
    ``COMMIT`` first, which would break the atomicity of the surrounding
    transaction.

    The import of ``SCHEMA_V3`` is deferred to the function body to keep the
    ``schema`` <-> ``migrations`` import cycle broken, exactly as
    :func:`_migrate_v1` does.
    """
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V3  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V3)


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Apply the v4 schema: the config key/value table (Wave 4).

    Creates the ``config`` table and seeds the ``config_version`` row in the
    ``meta`` table at ``0`` — the hot-load coordination counter that
    :mod:`appdb.config` bumps on every config write so every process can
    detect a change without a restart (web-redesign §5, Wave 4).

    Executes each DDL statement from :data:`appdb.schema.SCHEMA_V4`
    individually via ``conn.execute`` so every statement stays inside the
    single explicit transaction :func:`run_migrations` opens —
    ``conn.executescript`` is avoided because it issues an implicit
    ``COMMIT``. The ``config_version`` seed is one DML ``INSERT`` in the same
    transaction; ``meta`` already exists from migration v1.

    The import of ``SCHEMA_V4`` is deferred to the function body to break the
    ``appdb.schema`` ↔ ``appdb.migrations`` import cycle, exactly as
    :func:`_migrate_v1` does.
    """
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V4  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V4)
    # Seed the hot-load counter. INSERT OR IGNORE keeps the migration
    # idempotent and never clobbers a value a running deployment has bumped.
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('config_version', '0')"
    )


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Apply the v5 schema: daemon_status and reconcile_activity (Wave 6).

    Executes each DDL statement from :data:`appdb.schema.SCHEMA_V5`
    individually via ``conn.execute`` so every statement stays inside the
    single explicit transaction :func:`run_migrations` opens —
    ``conn.executescript`` is avoided because it issues an implicit
    ``COMMIT``.

    The import of ``SCHEMA_V5`` is deferred to the function body to break the
    ``appdb.schema`` ↔ ``appdb.migrations`` import cycle, exactly as
    :func:`_migrate_v1` does.
    """
    # Deferred import breaks the schema <-> migrations circular dependency.
    from appdb.schema import SCHEMA_V5  # noqa: PLC0415

    _apply_schema_string(conn, SCHEMA_V5)


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Migrate AI_MODELS to OCR_MODELS and CLASSIFY_MODELS (config split).

    If an ``AI_MODELS`` row exists in the ``config`` table, its value is
    copied to ``OCR_MODELS`` (only if absent) and ``CLASSIFY_MODELS`` (only
    if absent), then the ``AI_MODELS`` row is deleted. The ``config_version``
    counter is bumped once so every running process detects the change on its
    next hot-load check.

    Idempotent: running it a second time finds no ``AI_MODELS`` row and makes
    no further changes. This migration is called by :func:`run_migrations`
    inside an explicit ``BEGIN…COMMIT`` transaction, so partial failures roll
    back atomically.
    """
    row = conn.execute("SELECT value FROM config WHERE key = 'AI_MODELS'").fetchone()
    if row is None:
        return  # Nothing to migrate.

    legacy_value: str = row["value"]
    now = conn.execute("SELECT STRFTIME('%Y-%m-%dT%H:%M:%S+00:00', 'now')").fetchone()[
        0
    ]

    # Insert OCR_MODELS and CLASSIFY_MODELS only when they are absent so we
    # do not overwrite an operator who has already set one of them explicitly.
    for key in ("OCR_MODELS", "CLASSIFY_MODELS"):
        existing = conn.execute("SELECT 1 FROM config WHERE key = ?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)",
                (key, legacy_value, now),
            )

    # Remove the old key regardless.
    conn.execute("DELETE FROM config WHERE key = 'AI_MODELS'")

    # Bump config_version so hot-loading processes rebuild their Settings.
    # Inlined rather than imported from appdb.config to stay consistent with
    # the rest of this module (all deps are sqlite3 + structlog only).
    conn.execute(
        "UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) "
        "WHERE key = 'config_version'"
    )

    log.info("appdb.migration_v6_ai_models_split")


# Ordered (version, migration_function) pairs. The version is the
# schema_version written to meta after the migration commits. Entries must be
# in strictly ascending version order; the runner relies on it.
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply every pending migration to *conn* and advance ``schema_version``.

    Reads ``meta.schema_version`` (treated as 0 when the ``meta`` table or its
    row is absent — a fresh database has neither), then applies every
    migration whose version exceeds the current one, in ascending order, each
    inside its own ``BEGIN…COMMIT`` transaction. The new version is persisted
    in ``meta`` inside that same transaction.

    Args:
        conn: An open connection from :func:`appdb.connection.connect`.

    Raises:
        AppDbError: The stored ``schema_version`` exceeds the highest known
            migration version — the database was written by newer code, and
            proceeding could corrupt or misread the schema.
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
            # Persist the new version in the same transaction so a crash
            # rolls back to the pre-migration state entirely.
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

    Returns 0 when the ``meta`` table does not exist (a fresh database) or
    when its ``schema_version`` row is absent. Any OperationalError other than
    a missing ``meta`` table — a malformed disk image, a locked file —
    propagates rather than being masked as version 0, so a corrupt or busy
    ``app.db`` fails loud instead of being silently re-migrated (§1.11).

    Args:
        conn: An open SQLite connection.

    Returns:
        The stored ``schema_version`` as an integer, or 0 when absent.

    Raises:
        sqlite3.OperationalError: The query failed for a reason other than the
            ``meta`` table being absent.
    """
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError as exc:
        if _is_missing_table_error(exc):
            # The meta table does not exist yet — a fresh database.
            return 0
        # A malformed or locked database must fail loud, never be re-migrated.
        raise
    return int(row[0]) if row is not None else 0
