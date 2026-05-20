"""SQLite schema definition and connection factory for the search index store.

This module owns the DDL for every table, virtual table, and index in the
search index.  It also exposes the connect() factory that correctly
configures every new connection.

Allowed deps: sqlite3, sqlite-vec.
Forbidden: imports from any other internal package.
"""

from __future__ import annotations

import sqlite3

import sqlite_vec  # type: ignore[import-untyped]  # no stubs shipped with the package

# The schema version recorded in meta.schema_version.
# A later task (T1.2) will introduce a migration runner that reads this value
# and applies pending migrations.  For now, ensure_schema() applies _SCHEMA
# directly — all DDL uses IF NOT EXISTS, so repeated application is safe.
SCHEMA_VERSION: int = 1

# Verbatim DDL from SPEC §4.1.  All statements use IF NOT EXISTS so that
# ensure_schema() is idempotent for the v1 schema.
_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY,
    title            TEXT,
    correspondent_id INTEGER,
    document_type_id INTEGER,
    tag_ids          TEXT NOT NULL,
    created          TEXT,
    modified         TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    page_count       INTEGER,
    chunk_count      INTEGER,
    indexed_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taxonomy (
    kind  TEXT NOT NULL,
    id    INTEGER NOT NULL,
    name  TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    page_hint   INTEGER,
    embedding   BLOB NOT NULL
);

-- Standalone FTS5 (own text copy, no content= pointer) per SPEC §4.1/§4.5.
-- An external-content table does not auto-sync when chunks rows vanish via FK
-- cascade, which would silently leave a stale keyword index; the writer keeps
-- chunks_fts in step explicitly, by rowid, inside the same transaction.
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5 (
    text
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_modified
    ON documents (modified);

CREATE INDEX IF NOT EXISTS idx_documents_correspondent_id
    ON documents (correspondent_id);

CREATE INDEX IF NOT EXISTS idx_documents_document_type_id
    ON documents (document_type_id);

CREATE INDEX IF NOT EXISTS idx_documents_created
    ON documents (created);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);
"""


def connect(db_path: str, *, read_only: bool) -> sqlite3.Connection:
    """Open a connection to the search-index SQLite database.

    Loads the sqlite-vec extension, sets WAL journal mode, and applies the
    pragmas required by SPEC §4.5 and CODE_GUIDELINES §9.7.

    The *read_only* parameter documents the caller's intent but does NOT
    change how the file is opened.  Both paths open a normal read-write
    connection and load sqlite-vec.  A connection-level mode=ro URI is
    deliberately avoided: a read-only SQLite connection cannot maintain the
    WAL -shm coordination file while a separate writer process is live.
    Read-only access is enforced structurally — the StoreReader API has no
    write methods, and the indexer's flock makes it the sole writer.
    See SPEC §3.2 for the full rationale.

    Args:
        db_path: Filesystem path to the SQLite database file.
        read_only: Caller intent flag; does not affect the underlying
            connection mode (see above).

    Returns:
        A configured sqlite3.Connection with sqlite-vec loaded and WAL
        pragmas applied.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Load sqlite-vec for vec_distance_cosine and float32 blob helpers.
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # WAL mode enables one writer + concurrent readers across processes.
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL durability: safe with WAL; a crash can lose the last checkpoint
    # but never corrupt a committed transaction.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Enforce FK constraints so ON DELETE CASCADE is active.
    conn.execute("PRAGMA foreign_keys=ON")
    # Avoid indefinite hangs when another connection holds a write lock.
    conn.execute("PRAGMA busy_timeout=5000")

    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply the v1 schema to *conn* if it has not been applied yet.

    All DDL statements in _SCHEMA use IF NOT EXISTS, so this function is
    safe to call repeatedly on an existing database — it is a no-op when
    every object already exists.

    Note: a later task (T1.2) will replace this body with a versioned
    migration runner.  Do not import or reference any migrations module here;
    it does not exist yet.

    Args:
        conn: An open connection returned by connect().
    """
    conn.executescript(_SCHEMA)
