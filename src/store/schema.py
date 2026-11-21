"""Search-index DDL, the connection factory, and ``ensure_schema``."""

from __future__ import annotations

import sqlite3

# sqlite_vec ships no type stubs.
import sqlite_vec  # type: ignore[import-untyped]

from store.migrations import run_migrations

# Must equal the highest version in store.migrations.MIGRATIONS.
SCHEMA_VERSION: int = 2

# Every statement uses IF NOT EXISTS so applying it is idempotent.
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

-- Standalone FTS5 (own text copy, no content= pointer).
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

-- Backs the Library browse's default "recently added" sort
-- (ORDER BY indexed_at DESC, id DESC); without it that very common view does a
-- full table sort on every page request.
CREATE INDEX IF NOT EXISTS idx_documents_indexed_at
    ON documents (indexed_at);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open the search-index database with sqlite-vec loaded and WAL pragmas set.

    Always read-write, even for the StoreReader: a ``mode=ro`` connection cannot
    maintain the WAL ``-shm`` file while a separate writer process is live. The
    reader is read-only by API, and the indexer's flock makes it the sole writer.
    """
    # The StoreWriter shares one connection across worker threads behind its own
    # lock; without this flag sqlite3 rejects use from any other thread.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # An 8 KiB page fits a 1536-dim float32 embedding on one leaf page instead of
    # an overflow chain the vector scan must walk (~4% faster at 40k chunks).
    # Must precede journal_mode=WAL; SQLite only honours it on an empty file.
    conn.execute("PRAGMA page_size=8192")
    # WAL: one writer plus concurrent readers across processes.
    conn.execute("PRAGMA journal_mode=WAL")
    # Safe with WAL: a crash can lose the last checkpoint, never a commit.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Needed for ON DELETE CASCADE.
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")

    # Every query brute-force scans every embedding, so these trade memory for
    # read throughput (~93ms -> ~56ms per scan over 40k chunks, warm cache).
    # 256 MiB page cache (negative means KiB); also lets bulk backfill batch
    # dirty pages instead of thrashing the 2 MiB default.
    conn.execute("PRAGMA cache_size=-262144")
    # mmap serves embedding pages zero-copy; it only maps up to the file size, so
    # RSS tracks the database, not this ceiling.
    conn.execute("PRAGMA mmap_size=536870912")
    conn.execute("PRAGMA temp_store=MEMORY")

    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations; a no-op when the schema is current.

    Raises:
        store.migrations.StoreError: The database was written by a newer version.
    """
    run_migrations(conn)
