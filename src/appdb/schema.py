"""SQLite schema definition for the application database (``app.db``).

This module owns the DDL for every ``app.db`` table and index, and exposes
:func:`ensure_schema`, which delegates to the versioned migration runner in
:mod:`appdb.migrations`. ``SCHEMA_VERSION`` is the highest migration version
the current code knows; it is the single source of truth the migration
runner records in ``meta``.

The Wave 1 schema (migration v1) is the ``users`` and ``sessions`` tables of
spec §4.2. Wave 3 adds ``api_keys`` and Wave 4 adds ``config`` as further
migrations — each a new entry in :data:`appdb.migrations.MIGRATIONS`, never an
edit to v1.

Allowed deps: sqlite3, appdb.migrations. Forbidden: store, search, daemons.
"""

from __future__ import annotations

import sqlite3

from appdb.migrations import run_migrations

# The highest schema version the current code knows. Recorded in
# meta.schema_version by the migration runner after the last migration.
SCHEMA_VERSION: int = 1

# Migration v1 DDL — the users and sessions tables of spec §4.2, plus the
# three sessions indexes. Every statement uses IF NOT EXISTS so the migration
# is idempotent, although the runner only applies it when schema_version < 1.
#
# users: human accounts. password_hash is an argon2id encoded string. role
# and status are CHECK-constrained to the allowed values so a bad write fails
# at the database, not silently. username is UNIQUE NOT NULL.
#
# sessions: server-side sessions. token_hash is the SHA-256 hex of the
# opaque cookie token — the raw token is never stored. user_id cascades on
# delete so removing a user atomically revokes every session they hold.
SCHEMA_V1: str = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY,
    username            TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    display_name        TEXT,
    email               TEXT,
    role                TEXT NOT NULL
                            CHECK (role IN ('admin', 'member', 'readonly')),
    status              TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended')),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    last_login_at       TEXT,
    password_changed_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id            INTEGER PRIMARY KEY,
    token_hash    TEXT NOT NULL UNIQUE,
    user_id       INTEGER NOT NULL
                      REFERENCES users(id) ON DELETE CASCADE,
    created_at    TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    user_agent    TEXT,
    ip            TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_token_hash
    ON sessions (token_hash);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id
    ON sessions (user_id);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
    ON sessions (expires_at);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Bring ``app.db`` up to the latest schema by running pending migrations.

    Delegates to :func:`appdb.migrations.run_migrations`, which reads the
    stored ``schema_version`` from ``meta`` (treating a missing table or row
    as version 0), applies every migration whose version exceeds it in
    ascending order, and persists the new version after each.

    Safe to call repeatedly: when the database is already current it is a
    no-op.

    Args:
        conn: An open connection from :func:`appdb.connection.connect`.

    Raises:
        appdb.migrations.AppDbError: The database's ``schema_version`` is
            higher than :data:`SCHEMA_VERSION` — it was written by newer code.
    """
    run_migrations(conn)
