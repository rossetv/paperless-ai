"""SQLite schema definition for the application database (``app.db``).

This module owns the DDL for every ``app.db`` table and index, and exposes
:func:`ensure_schema`, which delegates to the versioned migration runner in
:mod:`appdb.migrations`. ``SCHEMA_VERSION`` is the highest migration version
the current code knows; it is the single source of truth the migration
runner records in ``meta``.

The Wave 1 schema (migration v1) is the ``users`` and ``sessions`` tables of
spec §4.2. Wave 2 adds ``recent_searches`` (migration v2); Wave 3 adds
``api_keys`` and Wave 4 adds ``config`` as further migrations — each a new
entry in :data:`appdb.migrations.MIGRATIONS`, never an edit to v1.

Allowed deps: sqlite3, appdb.migrations. Forbidden: store, search, daemons.
"""

from __future__ import annotations

import sqlite3

from appdb.migrations import run_migrations

# The highest schema version the current code knows. Recorded in
# meta.schema_version by the migration runner after the last migration.
SCHEMA_VERSION: int = 5

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

# Migration v2 DDL — the recent_searches table (web-redesign §5). One row per
# search a signed-in user runs; the search server keeps at most ~20 newest
# rows per user. user_id REFERENCES users(id) ON DELETE CASCADE so deleting
# an account drops their search history atomically. The composite index on
# (user_id, created_at) serves the per-user "newest first" list directly.
SCHEMA_V2: str = """
CREATE TABLE IF NOT EXISTS recent_searches (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL
                    REFERENCES users(id) ON DELETE CASCADE,
    query       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recent_searches_user_created
    ON recent_searches (user_id, created_at);
"""

# Migration v3 DDL — the api_keys table (web-redesign §5; Wave 3). A
# programmatic credential for the REST and MCP surfaces.
#
# key_hash is the SHA-256 hex of the raw key; the raw key (sk-pls-...) is
# never stored, so a database leak yields no usable credential. key_hash is
# UNIQUE — the bearer auth path looks a key up by this column. key_prefix is
# the first ~12 characters of the raw key, kept purely so the UI can show
# "sk-pls-AbC1..." without holding the secret.
#
# owner_user_id REFERENCES users(id) ON DELETE CASCADE: deleting a user
# atomically destroys every key they own. scopes is a comma-separated list
# drawn from api,mcp,admin. revoked_at being non-NULL means the key is dead;
# expires_at being non-NULL and in the past also kills it. request_count and
# last_used_at are updated by a throttled "touch" so auth is not a write per
# request.
SCHEMA_V3: str = """
CREATE TABLE IF NOT EXISTS api_keys (
    id             INTEGER PRIMARY KEY,
    key_hash       TEXT NOT NULL UNIQUE,
    key_prefix     TEXT NOT NULL,
    name           TEXT NOT NULL,
    owner_user_id  INTEGER NOT NULL
                       REFERENCES users(id) ON DELETE CASCADE,
    scopes         TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT,
    last_used_at   TEXT,
    revoked_at     TEXT,
    request_count  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash
    ON api_keys (key_hash);

CREATE INDEX IF NOT EXISTS idx_api_keys_owner_user_id
    ON api_keys (owner_user_id);
"""


# Migration v4 DDL — the config table (web-redesign spec §5, Wave 4). It holds
# the application's runtime configuration as raw string values keyed by the
# canonical environment-variable name. Wave 4 moves all 51 config settings out
# of environment variables and into this table; the two bootstrap variables
# APP_DB_PATH and INDEX_DB_PATH stay in the environment because they tell the
# process where this database lives.
#
# value is stored as TEXT and is the exact string form the env-var would have
# had — common.config parses and validates it, so the database stays a dumb
# store. updated_at is an ISO-8601 UTC timestamp of the last write, surfaced
# by the Settings screen.
SCHEMA_V4: str = """
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# Migration v5 DDL — the Index dashboard's cross-process state (web-redesign
# spec §5, Wave 6).
#
# daemon_status: one heartbeat row per daemon. Each of the four daemons
# (ocr, classifier, indexer, search) upserts its row on every work cycle.
# The dashboard's running/idle/stopped state is NOT stored — it is derived
# at read time from last_heartbeat recency, so a crashed daemon that writes
# nothing is correctly reported "stopped" without anyone having to write
# that. processed_count is a monotonic throughput counter the daemon owns.
#
# reconcile_activity: an append-only log of the indexer's reconcile/sweep
# cycles, so the dashboard can show "Recent activity". index.db keeps only
# the latest reconcile timestamp (one value, overwritten) and is destroyed
# by the destructive "Rebuild" action — this history lives in app.db
# precisely so a rebuild does not erase it. kind is CHECK-constrained to the
# two cycle kinds; summary is a JSON object of the SyncReport/SweepReport
# counts.
SCHEMA_V5: str = """
CREATE TABLE IF NOT EXISTS daemon_status (
    name            TEXT PRIMARY KEY
                        CHECK (name IN ('ocr', 'classifier',
                                        'indexer', 'search')),
    detail          TEXT NOT NULL,
    processed_count INTEGER NOT NULL DEFAULT 0,
    last_heartbeat  TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reconcile_activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL CHECK (kind IN ('sync', 'sweep')),
    started_at  TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    ok          INTEGER NOT NULL CHECK (ok IN (0, 1)),
    summary     TEXT NOT NULL,
    detail      TEXT NOT NULL
);
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
