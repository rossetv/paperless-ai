"""SQLite schema definition and connection factory for the search index store.

This module owns the DDL for every table, virtual table, and index in the
search index.  It also exposes the connect() factory that correctly
configures every new connection, and ensure_schema() which delegates to the
versioned migration runner in store.migrations.

Allowed deps: sqlite3, sqlite-vec, store.migrations.
Forbidden: imports from any package above store/ in the layer hierarchy.
"""

from __future__ import annotations

import sqlite3

# rationale: sqlite_vec ships no type stubs; untyped import is unavoidable.
import sqlite_vec  # type: ignore[import-untyped]

from store.migrations import run_migrations

# The schema version recorded in meta.schema_version. Must equal the highest
# version in store.migrations.MIGRATIONS.
SCHEMA_VERSION: int = 2

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

-- Backs the Library browse's default "recently added" sort
-- (ORDER BY indexed_at DESC, id DESC); without it that very common view does a
-- full table sort on every page request.
CREATE INDEX IF NOT EXISTS idx_documents_indexed_at
    ON documents (indexed_at);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection to the search-index SQLite database.

    Loads the sqlite-vec extension, sets WAL journal mode, and applies the
    pragmas required by SPEC §4.5 and CODE_GUIDELINES §9.7.

    Every connection is opened read-write.  A connection-level ``mode=ro`` URI
    is deliberately avoided even for the StoreReader: a read-only SQLite
    connection cannot maintain the WAL ``-shm`` coordination file while a
    separate writer process is live.  Read-only access for the search server
    is enforced structurally instead — the StoreReader API exposes no write
    methods, and the indexer's flock makes it the sole writer (SPEC §3.2).

    Args:
        db_path: Filesystem path to the SQLite database file.

    Returns:
        A configured sqlite3.Connection with sqlite-vec loaded and WAL
        pragmas applied.
    """
    # check_same_thread=False is required: the StoreWriter holds an internal
    # threading.Lock that serialises writes from multiple worker threads against
    # one shared connection.  Without this flag, Python's sqlite3 raises a
    # ProgrammingError when the lock-protected write is executed from any thread
    # other than the one that opened the connection (SPEC §5.6, §8.4).
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Load sqlite-vec for vec_distance_cosine and float32 blob helpers.
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # An 8 KiB page holds a 1536-dim float32 embedding (6,144 bytes) plus its
    # row header on a single leaf page, instead of spilling onto a 4 KiB
    # overflow-page chain that the brute-force vector scan must then traverse
    # for every chunk. Measured ~4% faster scans at 40k chunks. Must precede
    # journal_mode=WAL and any table creation — SQLite only honours a new
    # page_size on an as-yet-empty database file; on an existing index this is
    # a harmless no-op (the on-disk size is fixed until a VACUUM/rebuild).
    conn.execute("PRAGMA page_size=8192")
    # WAL mode enables one writer + concurrent readers across processes.
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL durability: safe with WAL; a crash can lose the last checkpoint
    # but never corrupt a committed transaction.
    conn.execute("PRAGMA synchronous=NORMAL")
    # Enforce FK constraints so ON DELETE CASCADE is active.
    conn.execute("PRAGMA foreign_keys=ON")
    # Avoid indefinite hangs when another connection holds a write lock.
    conn.execute("PRAGMA busy_timeout=5000")

    # Read-performance pragmas. The hot path is a brute-force vector scan that
    # reads every chunk's embedding BLOB (~6 KiB each) on every query, so the
    # working set is the whole embeddings column (hundreds of MB at scale).
    # These trade resident memory for read throughput — a deliberate win on the
    # RAM-rich deployment target. Measured: ~93ms -> ~56ms per scan over 40k
    # chunks (a ~40% reduction), reproducible warm-cache.
    #
    # 256 MiB page cache (negative => KiB) keeps hot index/leaf pages resident
    # and lets the indexer's bulk backfill batch dirty pages instead of
    # thrashing the 2 MiB default cache.
    conn.execute("PRAGMA cache_size=-262144")
    # 512 MiB memory-mapped reads serve committed embedding pages zero-copy,
    # eliminating the per-pread userspace memcpy that dominates a full scan.
    # mmap only maps up to the file size, so RSS tracks the DB, not this ceiling.
    conn.execute("PRAGMA mmap_size=536870912")
    # Keep transient B-trees and sort spills in memory rather than on disk.
    conn.execute("PRAGMA temp_store=MEMORY")

    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure the search index schema is up to date by running pending migrations.

    Delegates to store.migrations.run_migrations(), which reads the stored
    schema_version from the meta table (treating 0 as a fresh database),
    applies every migration whose version exceeds the current version in
    ascending order, and persists the new schema_version after each one.

    Safe to call repeatedly — when the stored schema_version already matches
    the highest known migration, run_migrations() is a no-op.

    Args:
        conn: An open connection returned by connect().

    Raises:
        store.migrations.StoreError: The database's schema_version is higher
            than the maximum known migration version (a future-version guard).
    """
    run_migrations(conn)
