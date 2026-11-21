"""DDL for every ``app.db`` table, applied by :mod:`appdb.migrations`."""

from __future__ import annotations

import sqlite3

from appdb.migrations import run_migrations

SCHEMA_VERSION: int = 8

# v1: users and sessions. role and status are CHECK-constrained so a bad write
# fails at the database. sessions.token_hash is the SHA-256 hex of the cookie
# token, which is never stored; deleting a user revokes all their sessions.
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

# v2: recent_searches, one row per search a signed-in user runs.
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

# v3: api_keys, credentials for the REST and MCP surfaces. Only the SHA-256 of
# the raw key is stored, so a database leak yields no usable credential;
# key_prefix lets the UI show "sk-pls-AbC1..." without the secret. A key is dead
# once revoked_at is set or expires_at has passed.
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


# v4: config, raw env-var strings keyed by name; common.config parses them.
# APP_DB_PATH and INDEX_DB_PATH stay in the environment because they say where
# this database lives.
SCHEMA_V4: str = """
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# v5: the Index dashboard's cross-process state. daemon_status stores no
# running/idle/stopped state; it is derived from last_heartbeat at read time.
# reconcile_activity lives here, not in index.db, so "Rebuild" does not erase
# it; summary is a JSON object of SyncReport/SweepReport counts.
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


# v7: api_key_usage, per-key daily LLM spend (usage_date is the UTC date).
# Usage cascades with its key: the cap belongs to a live credential, not an
# audit log. The composite primary key is the upsert target and serves the
# per-day lookup, so no separate index is needed.
SCHEMA_V7: str = """
CREATE TABLE IF NOT EXISTS api_key_usage (
    api_key_id  INTEGER NOT NULL
                    REFERENCES api_keys(id) ON DELETE CASCADE,
    usage_date  TEXT NOT NULL,
    tokens      INTEGER NOT NULL DEFAULT 0,
    calls       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key_id, usage_date)
);
"""


# v8: model_pricing, the cached USD price book. The provenance columns are
# denormalised onto every row because the whole cache is replaced atomically,
# so rows never disagree and one SELECT loads prices and provenance together.
SCHEMA_V8: str = """
CREATE TABLE IF NOT EXISTS model_pricing (
    model           TEXT PRIMARY KEY,
    input_per_mtok  REAL NOT NULL,
    output_per_mtok REAL NOT NULL,
    as_of           TEXT NOT NULL,
    source          TEXT NOT NULL,
    fetched_at      TEXT NOT NULL
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Bring ``app.db`` up to the latest schema; a no-op when already current.

    Raises:
        appdb.migrations.AppDbError: The database was written by newer code.
    """
    run_migrations(conn)
