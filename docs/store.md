# The Search Index Store

`src/store/` is the database layer for the semantic-search **index** (`index.db`). It owns every `sqlite3` call and every SQL string that touches the index. Callers — the indexer daemon on the write side, the search server on the read side — use typed, dataclass-returning methods; no raw SQL, no `sqlite3.Row`, and no connection objects cross the package boundary.

> **Two databases, two packages.** The index store (`src/store/`) is **separate** from the application database (`src/appdb/`, file `app.db`), which holds user accounts, sessions, API keys, runtime config, and daemon status. They are independent files with independent schemas and migration histories, so rebuilding the index never touches accounts or configuration. This document covers the index store only; `appdb/` owns all of `app.db`'s SQL by the same discipline.

---

## Schema

A single SQLite file at `INDEX_DB_PATH` (default `/data/index.db`). The DDL lives in `store/schema.py` as `CREATE TABLE IF NOT EXISTS` / `CREATE VIRTUAL TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` statements; there is no ORM. The current schema version is **2** (`SCHEMA_VERSION` in `schema.py`).

### `documents`

```sql
documents(
  id               INTEGER PRIMARY KEY,   -- the Paperless document id
  title            TEXT,
  correspondent_id INTEGER,               -- FK-by-value into taxonomy; nullable
  document_type_id INTEGER,               -- FK-by-value into taxonomy; nullable
  tag_ids          TEXT NOT NULL,         -- JSON array of tag ids
  created          TEXT,                  -- document date, normalised UTC ISO-8601
  modified         TEXT NOT NULL,         -- Paperless 'modified', normalised UTC ISO-8601
  content_hash     TEXT NOT NULL,         -- SHA-256 of OCR content
  page_count       INTEGER,
  chunk_count      INTEGER,
  indexed_at       TEXT NOT NULL          -- when this row was last written
)
```

`documents` stores correspondent and document-type **ids**, not names. The `taxonomy` table maps `(kind, id) → name` and is refreshed every reconciliation cycle — so a rename in Paperless updates one row and is instantly reflected everywhere, with zero document rewrites.

Dates are normalised to UTC ISO-8601 at the store boundary (via `common.clock`) so that lexicographic range comparisons — used by filtered search and the Library browse — are correct.

### `taxonomy`

```sql
taxonomy(
  kind  TEXT NOT NULL,   -- 'correspondent' | 'document_type' | 'tag'
  id    INTEGER NOT NULL,
  name  TEXT NOT NULL,
  PRIMARY KEY (kind, id)
)
```

Refreshed atomically (DELETE all, INSERT new) at the start of each reconciliation cycle.

### `chunks`

```sql
chunks(
  id          INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  text        TEXT NOT NULL,
  page_hint   INTEGER,      -- page number for citations; nullable
  embedding   BLOB NOT NULL -- float32 vector, sqlite-vec serialised
)
```

The embedding is a plain `BLOB` column, not a `vec0` virtual table. `sqlite-vec` is loaded as an extension to supply the `vec_distance_cosine` scalar function and the `serialize_float32` blob helper; the vector search itself is an exact full scan (see [Vector search](#vector-search) below).

**The rowid invariant:** `chunks.id == chunks_fts.rowid` is load-bearing — both `vector_search` and `keyword_search` key results back to a chunk by this id. `StoreWriter` inserts the `chunks` row first, captures the auto-assigned `id`, and uses it as the explicit `rowid` for the `chunks_fts` insert, all inside one transaction.

### `chunks_fts`

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5 (text)
```

A **standalone** FTS5 table (not an external-content table). It keeps its own copy of the chunk text, keyed by `rowid == chunks.id`. Standalone is chosen over external-content because an external-content table does not auto-sync when `chunks` rows vanish via FK cascade — instead the writer keeps `chunks_fts` in step explicitly, by rowid, inside every delete transaction.

### `meta`

```sql
meta(key TEXT PRIMARY KEY, value TEXT)
```

Key–value store for runtime state. Known keys:

| Key | Purpose |
|:---|:---|
| `schema_version` | Current migration version (currently 2) |
| `embedding_model` | Model name stored at last index build |
| `embedding_dimensions` | Vector width stored at last index build |
| `modified_watermark` | Highest Paperless `modified` timestamp seen by the incremental sync, minus a small overlap |
| `last_full_sweep_at` | Timestamp of the last completed deletion sweep |
| `last_reconcile_at` | Timestamp of the last completed reconciliation cycle |
| `failed_documents` | JSON object mapping `str(doc_id) → consecutive_failure_count` (the indexer's dead-letter ledger) |

### Indexes

```sql
CREATE INDEX idx_documents_modified         ON documents (modified);
CREATE INDEX idx_documents_correspondent_id ON documents (correspondent_id);
CREATE INDEX idx_documents_document_type_id ON documents (document_type_id);
CREATE INDEX idx_documents_created          ON documents (created);
CREATE INDEX idx_documents_indexed_at       ON documents (indexed_at);  -- v2
CREATE INDEX idx_chunks_document_id         ON chunks (document_id);
```

`idx_documents_indexed_at` (added in schema v2) backs the Library browse's default "recently added" sort (`ORDER BY indexed_at DESC, id DESC`); without it that very common view does a full-table sort on every page request.

---

## Connection Configuration: WAL and Performance Pragmas

Every connection opened by `store.schema.connect()` is configured identically. SQLite only honours a new `page_size` on an as-yet-empty database file, so it is set before `journal_mode=WAL` and any table creation; on an existing index it is a harmless no-op.

| Pragma | Value | Rationale |
|:---|:---|:---|
| `page_size` | `8192` | An 8 KiB page holds a 1536-dim float32 embedding (6,144 bytes) plus its row header on one leaf page, instead of spilling onto a 4 KiB overflow chain the brute-force scan must traverse for every chunk (~4% faster scans at 40k chunks) |
| `journal_mode` | `WAL` | One writer + concurrent readers across processes; no shared-lock contention |
| `synchronous` | `NORMAL` | Safe with WAL — a crash can lose the last checkpoint, never a committed transaction |
| `foreign_keys` | `ON` | Activates `ON DELETE CASCADE` on `chunks.document_id` |
| `busy_timeout` | `5000` ms | Prevents indefinite hangs when another connection holds a write lock |
| `cache_size` | `-262144` (256 MiB) | Keeps hot index/leaf pages resident and lets the indexer batch dirty pages during a bulk backfill instead of thrashing the 2 MiB default |
| `mmap_size` | `536870912` (512 MiB) | Memory-mapped reads serve committed embedding pages zero-copy, eliminating the per-`pread` userspace `memcpy` that dominates a full scan |
| `temp_store` | `MEMORY` | Keeps transient B-trees and sort spills in memory, not on disk |

The page-cache and mmap pragmas trade resident memory for read throughput — a deliberate win on the RAM-rich deployment target. Measured: a full vector scan over 40k chunks drops from ~93 ms to ~56 ms (≈40% faster), reproducible warm-cache. `mmap` only maps up to the file size, so resident memory tracks the database, not the 512 MiB ceiling.

Connections are opened with `check_same_thread=False`. This is required because `StoreWriter` shares one connection across the indexer's worker threads, serialised by an internal lock; without the flag Python's `sqlite3` raises a `ProgrammingError` when the lock-protected write runs on a thread other than the one that opened the connection.

A connection-level `mode=ro` URI is deliberately **not** used, even for the reader. A read-only SQLite connection cannot maintain the WAL `-shm` coordination file while a separate writer process is live. Read-only access is instead enforced structurally: the `StoreReader` API has no write methods, and the indexer's `flock` makes it the sole writer.

The indexer calls `checkpoint()` at the end of every reconciliation cycle (see below), so the search server never chases an unbounded WAL file.

---

## `StoreWriter` and `StoreReader` — the Sole-Writer Model

The store enforces a strict split: `StoreWriter` (`store/writer.py`) owns all writes; the `StoreReader` package (`store/reader/`) owns all reads. The indexer daemon constructs and holds one `StoreWriter`. The search server constructs and holds one `StoreReader`. No other code touches `sqlite3` for the index.

**`StoreWriter`** holds an internal `threading.Lock` (`_write_lock`) around every write transaction, so the indexer's worker pool can share one instance safely. It runs `ensure_schema()` on construction — migration happens once, automatically. (Its few read methods — `get_index_state`, `get_all_document_ids`, `read_meta` — need no lock; WAL allows concurrent reads on the same connection.)

**`StoreReader`** is a thin facade (`store/reader/_reader.py`) over three concept-modules — `_ranked` (vector/keyword search), `_lookups` (document/chunk/taxonomy/facet/stats/integrity reads), and `_browse` (the Library browse). It holds an internal `threading.Lock` (`_query_lock`) around every query, so the search server can call methods concurrently from many request threads on one shared instance.

### `StoreWriter` public methods

| Method | Purpose |
|:---|:---|
| `ensure_schema()` (called in `__init__`) | Run pending migrations |
| `get_index_state() → dict[int, IndexState]` | Current `(modified, content_hash)` per document |
| `get_all_document_ids() → set[int]` | All document ids in the index |
| `read_meta(key) / write_meta(key, value)` | Access the `meta` table |
| `upsert_document(meta, chunks)` | Atomic full upsert: delete old chunks, insert new, write the `documents` row |
| `update_metadata(meta)` | Metadata-only update; no re-chunk, no re-embed. Raises if zero rows match (the index has diverged) |
| `delete_documents(ids)` | Delete documents and all their chunks |
| `refresh_taxonomy(entries)` | Replace the entire taxonomy atomically |
| `check_embedding_model() → bool` | Detect a model/dimension mismatch; wipe chunks and reset the watermark if needed |
| `rebuild_index()` | Operator "Rebuild index": wipe all chunks, documents, taxonomy, and the watermark — preserving the embedding-model meta |
| `checkpoint()` | `PRAGMA optimize`, then a `wal_checkpoint(TRUNCATE)` |
| `close()` | Close the connection |

### `StoreReader` public methods

| Method | Purpose |
|:---|:---|
| `vector_search(query_embedding, k, filters)` | Exact cosine-distance KNN over the filtered set |
| `keyword_search(terms, k, filters)` | FTS5 BM25 search over the filtered set |
| `get_documents(ids) → list[IndexedDocument]` | Document rows with resolved taxonomy names |
| `get_document_summary(id) → DocumentSummary \| None` | One document row (with `page_count`) for the Library detail view |
| `get_chunks(ids) → list[ChunkHit]` | Chunk rows by id |
| `get_taxonomy(kind) → list[TaxonomyEntry]` | All entries of one kind, ordered by name |
| `list_facets() → FacetSet` | All taxonomy entries + the index's date range |
| `get_stats() → IndexStats` | Document count, chunk count, last reconcile timestamp, embedding model |
| `get_failed_documents() → list[FailedDocument]` | The indexer's dead-letter ledger, joined to titles, for the Index dashboard |
| `list_documents(query) → DocumentPage` | Paginated, sorted, filtered Library browse |
| `quick_check() → bool` | Run `PRAGMA quick_check` |
| `close()` | Close the connection |

`SearchFilters` — used by both search methods — is a frozen dataclass defined in `store/models.py` and re-exported from both `store/__init__.py` and `store/reader/__init__.py`:

```python
@dataclass(frozen=True, slots=True)
class SearchFilters:
    date_from: str | None          # lower bound on documents.created (inclusive)
    date_to: str | None            # upper bound on documents.created (inclusive)
    correspondent_id: int | None   # exact match
    document_type_id: int | None   # exact match
    tag_ids: tuple[int, ...]       # all ids must be present in documents.tag_ids
```

Filters are applied as SQL `WHERE` clauses *before* ranking, so filtered recall is exact — there is no "KNN returned k rows, all then filtered out" failure.

---

## Vector Search

`vector_search` performs an **exact scalar-distance KNN** over the filtered candidate set:

```sql
SELECT c.id, c.document_id, c.text, c.page_hint,
       vec_distance_cosine(c.embedding, :q) AS distance
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE <resolved filters on d>
ORDER BY distance
LIMIT :k
```

The query blob is passed straight to `vec_distance_cosine` with no per-row dimension check: `check_embedding_model()` wipes and rebuilds every chunk whenever the model or dimension changes, so all stored embeddings always share one width.

At the project's target scale of roughly 1,000–10,000 documents (tens of thousands of chunks) this full scan runs in single-digit-to-low-tens-of-milliseconds. An approximate-nearest-neighbour index is added only if measured against a real corpus to be necessary.

`keyword_search` runs FTS5 BM25 over the same filtered set via `FROM chunks_fts AS fts JOIN chunks c ON c.id = fts.rowid JOIN documents d ON d.id = c.document_id WHERE <filters> AND fts.text MATCH ?`. Each term is quoted (`escape_fts_term`) and the terms are combined with `AND`; the text is bound as a parameter.

The dynamic `WHERE` clauses are built by `store/reader/_filters.py` from a fixed whitelist of columns and `?` placeholders only — no caller value is ever spliced into a SQL string. Results from both searches are fused in the retriever with Reciprocal Rank Fusion (see [Search](search.md)).

---

## Migration Runner

`store/migrations.py` holds an ordered list of `(version, function)` pairs. On startup, `ensure_schema()` calls `run_migrations(conn)`, which:

1. Reads `meta.schema_version` (0 for a fresh database — a missing `meta` table is detected by the `no such table` marker and mapped to version 0; **any other** `OperationalError`, such as a malformed image or a locked file, propagates rather than being masked as fresh).
2. Raises `StoreError` if the stored version exceeds the highest known version — the database was written by newer code, and proceeding could corrupt or misinterpret the schema.
3. Applies each pending migration inside its own explicit `BEGIN` / `COMMIT`. The `schema_version` is persisted inside the same transaction, so a crash mid-migration rolls back entirely to the pre-migration state.

The registered migrations:

| Version | Migration |
|:---|:---|
| 1 | Create all tables, virtual tables, and indexes |
| 2 | Add `idx_documents_indexed_at` (the Library "added" sort) |

`conn.executescript()` is deliberately avoided in migration functions: it issues an implicit `COMMIT` before executing, which would break atomicity. Each DDL statement is executed individually with `conn.execute()` inside the surrounding transaction (comment lines are stripped first, so a `;` inside a comment cannot split into a broken fragment).

The mechanism exists from the first commit so that long-lived indexes never need a manual wipe to upgrade.

---

## Embedding-Model Change Rebuild

On startup, `StoreWriter.check_embedding_model()` compares `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` against `meta`:

- **Match** — returns `False`; no action needed.
- **Mismatch or first run** — wipes `chunks` and `chunks_fts`, keeps `documents` and `taxonomy` intact, clears `modified_watermark`, writes the new model name and dimensions to `meta`, and returns `True`. The next reconciliation cycle re-embeds everything from scratch (with the watermark cleared, the incremental sync sees no server-side filter and re-walks the whole archive).

Vectors from different embedding models or dimensions are incomparable; silently serving stale vectors would produce wrong results. Because a full re-embed is the single most expensive event in the system, `store/_reembed_guard.py` emits a **CRITICAL** `store.full_reembed_projected` log naming the trigger and the projected scope (document and chunk counts) *before* the wipe — so an unintended trigger (for example an unpinned `EMBEDDING_MODEL` changing under a Watchtower auto-update) is loud in the logs. The guard is observability only: a read error while projecting the scope degrades to a CRITICAL log with the scope marked unknown (`-1`) and the wipe proceeds — the wipe is correct and necessary; only its loudness is at stake. The same guard fires for the operator `rebuild_index()`.

---

## WAL Checkpoint and Planner Stats

`checkpoint()` runs at the end of every reconciliation cycle. It does two things, in order:

1. `PRAGMA optimize` — refreshes `sqlite_stat1` statistics. After a large backfill the tables have no stats, so the read-side planner (the search server's filter and browse queries) plans against default uniform-distribution assumptions and can pick a worse index. `optimize` is self-throttling — a no-op when nothing changed — so it is safe to call every cycle.
2. `PRAGMA wal_checkpoint(TRUNCATE)` — truncates the WAL so the search server never chases an unbounded file. Running `optimize` first folds its small `sqlite_stat1` write into the same truncation.

---

## Corruption Recovery

The index is a **derived artefact** — every byte is reconstructable from Paperless-ngx. There is no backup requirement.

`GET /api/healthz` on the search server runs `PRAGMA quick_check` (and `get_stats`) on every request and surfaces corruption as `503 index-corrupt`. The integrity scan and stats read run under the reader's lock and are offloaded to the thread pool so the Docker healthcheck never stalls the event loop. The three states are evaluated by `evaluate_index_health` in `search/routes.py`:

| Status | Meaning |
|:---|:---|
| `index-not-ready` | The DB file is absent; **or** it exists but the schema has not been applied (surfaced as `SchemaNotReadyError`); **or** the schema exists but `last_reconcile_at` is unset (reconciliation has never completed); **or** `get_stats` failed unexpectedly |
| `index-corrupt` | The schema and a `last_reconcile_at` timestamp are present, but `PRAGMA quick_check` reports corruption |
| `ok` | Schema present, at least one reconciliation completed, `quick_check` passed |

`SchemaNotReadyError` exists precisely so the healthz handler can tell "the indexer has not built the index yet" apart from genuine corruption without inspecting `sqlite3` internals — `sqlite3.connect` auto-creates an empty file the moment a path is opened, so a present-but-empty file is *not* a ready index.

### Operator runbook (rebuild from scratch)

There are two ways to force a full rebuild. Both are safe — `app.db` (accounts, keys, config) is a separate file and is untouched.

**In-app (preferred).** An admin triggers **Rebuild index** from the Index dashboard (`POST /api/index/rebuild`). The search server writes a `rebuild.request` sentinel beside `index.db`; the indexer consumes it at the top of its next cycle, calls `StoreWriter.rebuild_index()` (one transaction — the index is either wholly intact or wholly empty, never half-wiped), and the same cycle's incremental sync re-indexes the whole archive. No file deletion, no restart.

**Manual (when the index file itself is unreadable).** If `quick_check` fails so hard the DB cannot be opened:

1. Observe `503 index-corrupt` from `GET /api/healthz`.
2. Stop the indexer daemon.
3. Delete `<INDEX_DB_PATH>` and its companion lock and WAL files (e.g. `rm /data/index.db /data/index.db.lock /data/index.db-wal /data/index.db-shm`).
4. Restart the indexer daemon. The next reconciliation rebuilds the index from an empty store — a full backfill that re-embeds every document.
5. Monitor progress on the Index dashboard (`GET /api/index/status`, which reports the indexer heartbeat and document count). `GET /api/stats` shows the same counts but requires an authenticated Read-only-or-above caller; the search server keeps returning `503 index-not-ready` from `healthz` until the first reconciliation completes.

---

## FK Cascade and FTS5

`chunks` declares `REFERENCES documents(id) ON DELETE CASCADE`, so deleting a `documents` row automatically removes its `chunks` rows. The `chunks_fts` FTS5 virtual table is **standalone** (not `content=chunks`) and does **not** honour FK cascade.

Every delete operation in `StoreWriter` therefore follows this sequence within one transaction:

1. Collect the `chunks.id` values for the target document(s).
2. Delete from `chunks_fts` by rowid explicitly.
3. Delete from `documents` (the cascade removes `chunks`).

This ordering is documented at the delete site with a `# why` comment. The same step-1-before-delete ordering is why the per-document upsert deletes the document's old chunks first (while the ids are still available) before re-inserting.

---

## Data Models (`store/models.py`)

All values crossing the store boundary are frozen dataclasses with `slots=True`:

| Class | Crosses boundary |
|:---|:---|
| `DocumentMeta` | Input to `upsert_document` / `update_metadata` |
| `ChunkInput` | Input to `upsert_document` — one chunk + embedding |
| `TaxonomyEntry` | Input to `refresh_taxonomy`; output of `list_facets` / `get_taxonomy` |
| `SearchFilters` | Input to `vector_search` / `keyword_search` |
| `DocumentBrowseQuery` | Input to `list_documents` |
| `IndexState` | Output of `get_index_state` |
| `ChunkHit` | Output of `vector_search` / `keyword_search` / `get_chunks` |
| `IndexedDocument` | Output of `get_documents` — row joined to taxonomy names |
| `DocumentSummary` | Output of `get_document_summary` — like `IndexedDocument` plus `page_count` |
| `DocumentPage` | Output of `list_documents` — a page of `DocumentSummary` plus the total match count |
| `FacetSet` | Output of `list_facets` |
| `IndexStats` | Output of `get_stats` |
| `FailedDocument` | Output of `get_failed_documents` — the dead-letter ledger for the dashboard |
