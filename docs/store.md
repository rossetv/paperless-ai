# The Search Index Store

`src/store/` is the single database layer for the semantic-search subsystem. It owns every `sqlite3` call and every SQL string in the codebase. All callers — the indexer daemon (write side) and the search pipeline (read side) — use typed, dataclass-returning methods; no raw SQL, no `sqlite3.Row`, no connection objects cross the package boundary.

---

## Schema

A single SQLite file at `INDEX_DB_PATH` (default `/data/index.db`). The schema is declared in `store/schema.py` as `CREATE TABLE IF NOT EXISTS` / `CREATE VIRTUAL TABLE IF NOT EXISTS` statements; there is no ORM.

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
  indexed_at       TEXT NOT NULL
)
```

`documents` stores correspondent and document-type **ids**, not names. A `taxonomy` table maps `(kind, id) → name` and is refreshed every reconciliation cycle — so a rename in Paperless updates one row and is instantly reflected everywhere, with zero document rewrites.

Dates are normalised to UTC ISO-8601 at the store boundary so that lexicographic range comparisons (used in filtered search) are correct.

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

The embedding is a plain `BLOB` column, not a `vec0` virtual table. `sqlite-vec` is loaded as an extension to supply the `vec_distance_cosine` scalar function and the `serialize_float32` / `deserialize_float32` helpers; the vector search itself is an exact full-scan (see [Vector search](#vector-search) below).

**The rowid invariant:** `chunks.id == chunks_fts.rowid` is load-bearing — both `vector_search` and `keyword_search` key results back to a chunk by this id. The `StoreWriter` inserts the `chunks` row first, captures the auto-assigned `id`, and uses it as the explicit `rowid` for the `chunks_fts` insert, inside one transaction.

### `chunks_fts`

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5 (text)
```

A **standalone** FTS5 table (not an external-content table). It stores its own copy of the chunk text keyed by `rowid == chunks.id`. Standalone is chosen over external-content because an external-content table does not auto-sync when `chunks` rows vanish via FK cascade — the writer keeps `chunks_fts` in step explicitly, by rowid, inside every delete transaction.

### `meta`

```sql
meta(key TEXT PRIMARY KEY, value TEXT)
```

Key–value store for runtime state. Known keys:

| Key | Purpose |
|:---|:---|
| `schema_version` | Current migration version |
| `embedding_model` | Model name stored at last index build |
| `embedding_dimensions` | Vector width stored at last index build |
| `modified_watermark` | Highest Paperless `modified` timestamp seen by the incremental sync |
| `last_full_sweep_at` | Timestamp of the last completed deletion sweep |
| `last_reconcile_at` | Timestamp of the last completed reconciliation cycle |
| `failed_documents` | JSON object mapping document id → consecutive failure count |

### Indexes

```sql
CREATE INDEX idx_documents_modified       ON documents (modified);
CREATE INDEX idx_documents_correspondent_id ON documents (correspondent_id);
CREATE INDEX idx_documents_document_type_id ON documents (document_type_id);
CREATE INDEX idx_documents_created        ON documents (created);
CREATE INDEX idx_chunks_document_id       ON chunks (document_id);
```

---

## WAL Mode and Crash-Safety Pragmas

Every connection opened by `store/schema.connect()` applies the following:

| Pragma | Value | Rationale |
|:---|:---|:---|
| `journal_mode` | `WAL` | One writer + concurrent readers across processes; no shared lock contention |
| `synchronous` | `NORMAL` | Safe with WAL — a crash can lose the last checkpoint, never a committed transaction |
| `foreign_keys` | `ON` | Activates `ON DELETE CASCADE` on `chunks.document_id` |
| `busy_timeout` | `5000` ms | Prevents indefinite hangs when another connection holds a write lock |

A connection-level `mode=ro` URI is deliberately **not** used. A read-only SQLite connection cannot maintain the WAL `-shm` coordination file while a separate writer process is live. Read-only access is instead enforced structurally: the `StoreReader` API has no write methods, and the indexer's `flock` makes it the sole writer.

The indexer calls `PRAGMA wal_checkpoint(TRUNCATE)` at the end of every reconciliation cycle so the search server never chases an unbounded WAL file.

---

## `StoreWriter` and `StoreReader` — the Sole-Writer Model

The store enforces a strict split: `StoreWriter` owns all writes; `StoreReader` owns all reads. The indexer daemon constructs and holds one `StoreWriter`. The search server constructs and holds one `StoreReader`. No other code touches `sqlite3` directly.

**`StoreWriter`** holds an internal `threading.Lock` (`_write_lock`) around every write transaction, so the indexer's worker pool can share one `StoreWriter` instance safely. It also runs `ensure_schema()` on construction — schema migration happens once, automatically.

**`StoreReader`** holds an internal `threading.Lock` (`_query_lock`) around every query, allowing the search server to call methods concurrently from multiple request threads on one shared instance.

### `StoreWriter` public methods

| Method | Purpose |
|:---|:---|
| `ensure_schema()` (called in `__init__`) | Run pending migrations |
| `get_index_state() → dict[int, IndexState]` | Current `(modified, content_hash)` per document |
| `get_all_document_ids() → set[int]` | All document ids in the index |
| `upsert_document(meta, chunks)` | Atomic full upsert: delete old chunks, insert new |
| `update_metadata(meta)` | Metadata-only update; no re-chunk, no re-embed |
| `delete_documents(ids)` | Delete documents and all their chunks |
| `refresh_taxonomy(entries)` | Replace the entire taxonomy atomically |
| `read_meta(key) / write_meta(key, value)` | Access the meta table |
| `check_embedding_model() → bool` | Detect model mismatch; wipe and reset if needed |
| `checkpoint()` | WAL checkpoint (TRUNCATE mode) |

### `StoreReader` public methods

| Method | Purpose |
|:---|:---|
| `vector_search(query_embedding, k, filters)` | Exact cosine-distance KNN over the filtered set |
| `keyword_search(terms, k, filters)` | FTS5 BM25 search over the filtered set |
| `get_documents(ids) → list[IndexedDocument]` | Document rows with resolved taxonomy names |
| `get_chunks(ids) → list[ChunkHit]` | Chunk rows by id |
| `list_facets() → FacetSet` | All taxonomy entries + date range |
| `get_stats() → IndexStats` | Document count, chunk count, last reconcile timestamp |
| `quick_check() → bool` | Run `PRAGMA quick_check` |

`SearchFilters` — used by both search methods — is a frozen dataclass in `store/reader.py`:

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

At the project's target scale of roughly 1,000–10,000 documents (tens of thousands of chunks) this full scan runs in single-digit milliseconds. An approximate-nearest-neighbour index is added only when measured against a real corpus to be necessary.

`keyword_search` runs FTS5 BM25 over the same filtered set via a `JOIN chunks_fts AS fts JOIN chunks c ON c.id = fts.rowid JOIN documents d ON d.id = c.document_id WHERE <filters> AND fts.text MATCH ?`.

Results from both searches are fused in the retriever with Reciprocal Rank Fusion (see [Search](search.md)).

---

## Migration Runner

`store/migrations.py` maintains an ordered list of `(version, function)` pairs. On startup, `run_migrations(conn)`:

1. Reads `meta.schema_version` (0 for a fresh database with no `meta` table).
2. Raises `StoreError` if the stored version exceeds the highest known version — the database was written by a newer code version; proceeding could corrupt or misinterpret the schema.
3. Applies each pending migration inside its own `BEGIN` / `COMMIT` transaction. The `schema_version` is persisted inside the same transaction — a crash mid-migration rolls back entirely to the pre-migration state.

v1 of the schema is "create all tables, virtual tables, and indexes". The mechanism exists from the first commit so long-lived indexes never need a manual wipe to upgrade.

`conn.executescript()` is deliberately not used in migration functions: it issues an implicit `COMMIT` before executing, which would break atomicity. Each DDL statement is executed individually with `conn.execute()` inside the surrounding transaction.

---

## Embedding-Model Change Rebuild

On startup, `StoreWriter.check_embedding_model()` compares `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` against `meta`:

- **Match** — returns `False`; no action needed.
- **Mismatch or first run** — wipes `chunks` and `chunks_fts`, keeps `documents` and `taxonomy` intact, clears `modified_watermark`, writes the new model name and dimensions to `meta`, returns `True`. The next reconciliation cycle re-embeds everything from scratch.

Vectors from different embedding models or different dimensions are incomparable; silently serving stale vectors would produce wrong search results. The rebuild is logged at `WARNING` so the operator is not surprised by a full re-index.

---

## Corruption Recovery

The index is a **derived artefact** — every byte is reconstructable from Paperless-ngx. There is no backup requirement.

`GET /api/healthz` runs `PRAGMA quick_check` on every request. A failure is surfaced as `503 index-corrupt`. The operator runbook:

1. Observe `503 index-corrupt` from `GET /api/healthz`.
2. Stop the indexer daemon.
3. Delete `<INDEX_DB_PATH>` and `<INDEX_DB_PATH>.lock` (e.g. `rm /data/index.db /data/index.db.lock`).
4. Restart the indexer daemon. The next reconciliation rebuilds the index from an empty store — a full backfill that re-embeds all documents (approximately $0.60 and a few hours at 10k documents).
5. Monitor `GET /api/stats` for an advancing `last_reconcile_at` and a growing `document_count`. The search server returns `503 index-not-ready` until the first reconciliation completes.

The three `503` states:

| Status | Meaning |
|:---|:---|
| `index-not-ready` | The DB file is absent, or exists but the schema has not been applied (indexer has not run yet), or the schema exists but reconciliation has never completed |
| `index-corrupt` | The DB exists with a schema and a `last_reconcile_at` timestamp, but `PRAGMA quick_check` reports corruption |
| `ok` | Schema present, at least one reconciliation completed, `quick_check` passed |

---

## FK Cascade and FTS5

`chunks` declares `REFERENCES documents(id) ON DELETE CASCADE`, so deleting a `documents` row automatically removes its `chunks` rows. The `chunks_fts` FTS5 virtual table is **standalone** (not `content=chunks`) and does **not** honour FK cascade.

Every delete operation in `StoreWriter` therefore follows this sequence within one transaction:

1. Collect the `chunks.id` values for the target document(s).
2. Delete from `chunks_fts` by rowid explicitly.
3. Delete from `documents` (cascade removes `chunks`).

This ordering is documented at the delete site with a `# why` comment.

---

## Data Models (`store/models.py`)

All values crossing the store boundary are frozen dataclasses with `slots=True`:

| Class | Crosses boundary |
|:---|:---|
| `DocumentMeta` | Input to `upsert_document` / `update_metadata` |
| `ChunkInput` | Input to `upsert_document` — one chunk + embedding |
| `TaxonomyEntry` | Input to `refresh_taxonomy`; output of `list_facets` |
| `IndexState` | Output of `get_index_state` |
| `ChunkHit` | Output of `vector_search` / `keyword_search` |
| `IndexedDocument` | Output of `get_documents` — row joined to taxonomy names |
| `FacetSet` | Output of `list_facets` |
| `IndexStats` | Output of `get_stats` |
