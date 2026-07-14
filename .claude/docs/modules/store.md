<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: store

## Purpose

The persistence layer for the SQLite search index (`index.db`): the only package that holds sqlite3 connections to the index and builds its SQL. It exposes exactly two API classes over one schema — `StoreWriter` (write side, indexer daemon only) and `StoreReader` (read side, search server / MCP only) — plus versioned migrations, a connection factory carrying the WAL and performance pragmas, and the frozen dataclasses in `store.models` that are the only shapes allowed to cross the store boundary (raw `sqlite3.Row` objects never leave `src/store/`).

It stores documents, their chunks with float32 embeddings (sqlite-vec), a standalone FTS5 keyword index, a taxonomy table (correspondents / document types / tags), and a `meta` key-value table. No business logic, no HTTP, no LLM calls.

Caveat: `src/store/__init__.py`'s docstring claims the package owns *every* sqlite3 call in the codebase. That is no longer literally true — `src/appdb/` is a deliberately separate database (`app.db`: accounts, sessions, config) that copies, rather than shares, this package's migration machinery.

## Key files

| File | Role |
|------|------|
| `src/store/schema.py` | The full DDL (`_SCHEMA`, applied verbatim by `_migrate_v1`), `SCHEMA_VERSION = 2`, `connect(db_path)` (loads sqlite-vec; `page_size=8192`, WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `cache_size=-262144`, `mmap_size=536870912`, `temp_store=MEMORY`, `check_same_thread=False`, `row_factory=sqlite3.Row`), and `ensure_schema(conn)` → migration runner. Tables: `documents`, `taxonomy`, `chunks`, `chunks_fts` (FTS5 virtual), `meta`; indexes on `documents.modified` / `.correspondent_id` / `.document_type_id` / `.created` / `.indexed_at` and `chunks.document_id`. |
| `src/store/migrations.py` | `StoreError` (base) and `SchemaNotReadyError`, `_is_missing_table_error`, `MIGRATIONS = [(1, _migrate_v1), (2, _migrate_v2)]`, and `run_migrations(conn)` — reads `meta.schema_version` (0 = fresh), raises `StoreError` on a future version, applies each pending migration inside an explicit `BEGIN` / commit / rollback with the version write in the same transaction. |
| `src/store/models.py` | The 17 frozen slots dataclasses that cross the store boundary: `IndexState`, `DocumentMeta`, `ChunkInput`, `TaxonomyEntry`, `ChunkHit`, `FailedDocument`, `IndexedDocument`, `FacetSet`, `SearchFilters`, `IndexStats`, `DocumentSummary`, `DocumentBrowseQuery`, `DocumentPage`, `KeywordHit`, `KeywordPage`, `FilterFacet`, `FilterCatalog`. |
| `src/store/writer.py` | `StoreWriter` — the sole write interface. Reads: `get_index_state`, `get_all_document_ids`, `read_meta`. Writes (serialised by an internal `threading.Lock`): `write_meta`, `upsert_document`, `update_metadata`, `delete_documents`, `refresh_taxonomy`, `check_embedding_model`, `rebuild_index`, plus `_wipe_and_stamp_model` (the shared full wipe) and `checkpoint()` (`PRAGMA optimize` + `wal_checkpoint(TRUNCATE)`). Every `sqlite3.Error` is wrapped in `StoreError`. |
| `src/store/reader/_reader.py` | The `StoreReader` facade — owns the connection and a `threading.Lock` serialising every query, delegating to the three concept-modules. Its `keyword_document_search` is the one method with real logic here: it resolves each hit's `DocumentSummary` and builds the 280-char collapsed snippet, skipping documents pruned between the FTS match and the lookup. |
| `src/store/reader/_ranked.py` | Ranked retrieval: `vector_search` (brute-force `vec_distance_cosine` KNN over the SQL-filtered candidate set), `keyword_search` (FTS5 `bm25()` over `chunks_fts`), `keyword_document_search` (two CTEs — bm25 per chunk, then `ROW_NUMBER()` to keep each document's best chunk — returning `(rows, total)`). |
| `src/store/reader/_lookups.py` | Non-ranked reads: `get_documents`, `get_document_summary`, `get_chunks`, `get_taxonomy`, `list_facets`, `list_filters_with_counts`, `get_stats`, `get_failed_documents`, `quick_check`, plus the private tag helpers `_parse_tag_ids` / `_resolve_tag_names` / `_names_for_tag_ids`. The largest file in the module (639 lines). |
| `src/store/reader/_browse.py` | `list_documents` — the Library browse: the `_SORT_COLUMNS` whitelist (`created` / `title` / `indexed_at` → fixed column expressions), `_order_by` (raises `ValueError` on an unknown sort), and the count + page query pair run under one held lock so `total` is consistent with the returned rows. |
| `src/store/reader/_filters.py` | SQL fragment builders: `build_filters(SearchFilters)` (date range, correspondent, document type, tag membership via `EXISTS (SELECT 1 FROM json_each(d.tag_ids) WHERE value = ?)`), `_exclusive_upper_bound` (half-open `date_to + 1 day`, keeping the index sargable), `escape_fts_term` (doubles embedded `"`), `_escape_like_term` + `build_browse_where` (case-insensitive LIKE across `d.title` / `corr.name` / `dtype.name`). |
| `src/store/_sql.py` | 40 lines. `placeholders(count)` → `"?,?,?"` — the only sanctioned dynamic-SQL pattern in the codebase (`IN (...)`). Raises `ValueError` on a negative count; only the *count* of `?` is interpolated, every value binds. |
| `src/store/_reembed_guard.py` | Observability-only cost guard: `project_reembed_scope` (document/chunk counts, degrading to `(-1, -1)` on a read error) and `log_reembed_projection` — emits a CRITICAL `store.full_reembed_projected` before any full-index wipe (embedding-model change or operator rebuild). It never gates the wipe. |
| `tests/unit/store/conftest.py` | Shared fixtures: `db_path` (tmp_path), `unit_vec(dimensions, axis)` (axis-aligned vectors, so cosine distances are exactly 0.0 or 1.0), and `populated_db` (two documents × 2 chunks, a five-entry taxonomy, meta). Real `StoreWriter` / `StoreReader` are opened via `tests/helpers/store.py` (`open_writer` / `open_reader`) — nothing is mocked. |

## Entry points

| Side | Class | Constructed at |
|------|-------|----------------|
| Write | `StoreWriter(settings)` — `src/store/writer.py` | `src/indexer/daemon/_boot.py:134` (once; construction opens the connection and runs pending migrations) |
| Read | `StoreReader(settings)` — `src/store/reader/_reader.py`, re-exported from `store.reader` | `src/search/api.py:505` (lazy import, so `sqlite-vec` is not loaded eagerly) |

`src/store/__init__.py` re-exports only `StoreError`, `SchemaNotReadyError`, and `SearchFilters`. `StoreReader` / `StoreWriter` are imported from their submodules by design.

## Invariants

- **`chunks.id == chunks_fts.rowid`.** `upsert_document` inserts each chunk row individually purely to capture `cursor.lastrowid`, then batch-inserts `(rowid, text)` into `chunks_fts` with that exact id. Every keyword query joins `chunks c ON c.id = fts.rowid` and would silently return the wrong text if this broke. Tested in `tests/unit/store/test_writer.py::TestChunksFtsRowidInvariant`.
- **Every delete path must clear `chunks_fts` explicitly, by rowid, first.** `chunks_fts` is a standalone FTS5 table (no `content=` pointer), so it does **not** honour the FK `ON DELETE CASCADE` on `chunks.document_id`. `_delete_fts_rows` and `_delete_chunks_for_document` in `writer.py` exist for exactly this; a new delete path without them leaves a stale keyword index.
- **`store` is the only owner of `index.db` SQL.** No sqlite3 call and no SQL string for the search index exists outside `src/store/` (CODE_GUIDELINES §9.1). `src/appdb/` is a separate database with its own copied migration machinery and is explicitly not part of `store`.
- **Only `?` placeholders and fixed-whitelist values are ever interpolated into SQL.** The three whitelists: `placeholders(n)` (a run of `?` from an int), `_SORT_COLUMNS` in `_browse.py`, and the fixed clause fragments in `_filters.py`. Every caller value binds as a parameter; each interpolation site carries a `# nosec B608` naming its provenance.
- **All stored embeddings share one width.** `check_embedding_model()` wipes and re-embeds the whole index whenever the `(provider, model, dimensions)` triple changes — which is why `vector_search` passes the query blob straight to `vec_distance_cosine` with no per-row dimension check (see the module-level comment in `_ranked.py`).
- **`SCHEMA_VERSION` (schema.py) == `MIGRATIONS[-1][0]` (migrations.py).** Enforced by `tests/unit/store/test_schema.py::TestEnsureSchema::test_schema_version_constant_matches_latest_migration`.
- **Filters are applied as a WHERE on `documents` *before* ranking** in all three ranked queries, so there is no "rank k rows, then filter them all away" recall failure.
- **sqlite3 exception types never escape the package.** Every `sqlite3.Error` is caught and re-raised as `StoreError` (with `from`). The single typed exception is `SchemaNotReadyError` (a `StoreError` subclass) for a "no such table" read, raised only by `list_facets`, `list_filters_with_counts`, `get_stats`, and `get_failed_documents`.
- **`StoreReader` exposes no write method.** Read-only access is structural, not enforced by the connection — see the `mode=ro` gotcha below.
- **Both connections are shared across threads under a lock.** Writes are serialised by `StoreWriter`'s `threading.Lock` (indexer worker threads share one instance); reads by `StoreReader`'s `threading.Lock` (search request threads share one instance). Both connections open with `check_same_thread=False` precisely because of this.

## Gotchas

- **`connect()` always opens the database READ-WRITE, even for `StoreReader`.** A connection-level `mode=ro` URI is deliberately avoided: a read-only SQLite connection cannot maintain the WAL `-shm` coordination file while a separate writer process is live. Do not "harden" this — it breaks WAL coordination with the indexer (`src/store/schema.py:94-113`; `tests/unit/store/test_schema.py::TestConnect::test_connect_always_opens_read_write`).
- **`_migrate_v1` deliberately does not use `conn.executescript()`** — that issues an implicit COMMIT and would break the atomicity of `run_migrations`' explicit `BEGIN`. It strips `--` comment lines and splits `_SCHEMA` on `;`. Consequence: any new DDL statement in `_SCHEMA` must not contain a `;` inside a string literal or a trailing inline comment, or the split yields a broken fragment. Guarded by `tests/unit/store/test_migrations.py::TestMigrationAtomicity::test_v1_migration_uses_execute_not_executescript`.
- **`PRAGMA page_size=8192` must stay before `journal_mode=WAL` and any table creation** — SQLite only honours a new page size on an as-yet-empty file. On an existing index it is a silent no-op until a VACUUM/rebuild.
- **A missing `embedding_provider` meta key reads as `"openai"`.** This back-compat default in `check_embedding_model()` is load-bearing: without it every pre-existing production OpenAI index (whose meta predates the provider field) would read as a provider mismatch on the next boot and trigger a full, expensive re-embed of the whole library.
- **The identity wipe must delete `documents`, not just `chunks`.** Keeping the document rows lets the reconciler's content-hash check classify everything as unchanged and take a metadata-only pass — leaving the index permanently chunk-less (an empty search index). `_wipe_and_stamp_model` deletes `chunks_fts`, `chunks`, `documents`, `taxonomy` and the `modified_watermark` meta key, and stamps the new identity, all in one transaction.
- **A malformed `date_to` silently widens the result set.** `_exclusive_upper_bound(date_to)` returns `None` for an unparseable value and `build_filters` then omits the upper bound rather than raising. Deliberate (the value crosses an untrusted boundary — UI query param and LLM planner), but surprising.
- **`escape_fts_term` only doubles embedded double-quotes; the CALLER re-wraps each term** (`f'"{escape_fts_term(term)}"'`). This neutralises FTS5 boolean operators only because each element is a single user token. Never pass a pre-built MATCH expression as one `term` and expect boolean behaviour — it becomes one literal phrase.
- **`update_metadata` raises `StoreError` when 0 rows are updated** (the document vanished from the index) — a deliberate fail-loud, not a silent no-op. Callers must handle it.
- **Tag resolution never fails, it just loses tags.** `_names_for_tag_ids` silently drops tag ids with no taxonomy row, and `_parse_tag_ids` degrades a corrupt/NULL `tag_ids` column to an empty list (with a warning log) rather than raising.
- **`StoreWriter.checkpoint()` is the one write-ish method that does NOT take `_write_lock`** — it runs `PRAGMA optimize` then `PRAGMA wal_checkpoint(TRUNCATE)` directly on the connection. It is called once per cycle from the indexer loop (`src/indexer/daemon/_loop.py:294`), where no other write is in flight.
- **`reader.keyword_document_search` returns an EMPTY page when `terms` is empty.** The "filter-only browse" case that `KeywordHit`'s docstring describes (`snippet=None`, `rank=0.0`) is constructed in the search layer (`src/search/core.py:722-724`, from `list_documents`), not by the store.
- **The `meta` table is a shared, untyped key/value surface split across packages.** The store writes `schema_version`, `embedding_provider`, `embedding_model`, `embedding_dimensions`; the indexer writes `modified_watermark`, `last_reconcile_at` (`src/indexer/reconciler/_incremental.py`), `last_full_sweep_at` (`_sweep.py`) and the `failed_documents` JSON map (`_failed_documents.py`); the reader parses several back (`get_stats`, `get_failed_documents`). `_parse_failed_documents` tolerates any corrupt value by returning `{}`.
- **`store/__init__.py` re-exports only the exception types and `SearchFilters`.** `StoreReader` / `StoreWriter` are intentionally left out so `import store` does not eagerly load the sqlite-vec extension. Keep it that way.
- **`documents.tag_ids` is a JSON array string** (written with `json.dumps`), and tag filtering depends on it being valid JSON for `json_each()`. Any writer path storing a non-JSON value silently breaks tag filters.

## Extension points

| Change | Where |
|--------|-------|
| New table / index / column | Add DDL to `_SCHEMA` in `src/store/schema.py` (no `;` inside literals or inline comments), append `(N, _migrate_vN)` to `MIGRATIONS` in `src/store/migrations.py`, and bump `SCHEMA_VERSION` to match. |
| New boundary shape | Add a frozen slots dataclass to `src/store/models.py` — nothing else may cross the store boundary. |
| New filter predicate | Extend `build_filters` in `src/store/reader/_filters.py` (fixed fragment + bound `?`), and the corresponding field on `SearchFilters` / `DocumentBrowseQuery`. |
| New browse sort key | Add the column expression to `_SORT_COLUMNS` in `src/store/reader/_browse.py`; anything outside the whitelist raises `ValueError`. |
| New read query | Put it in the matching concept-module (`_ranked` / `_lookups` / `_browse`) taking `(conn, query_lock, …)`, and delegate to it from the `StoreReader` facade. |
| New write path | `src/store/writer.py`, under `_write_lock` and inside `with self._conn:` — and it must delete `chunks_fts` rows explicitly if it removes chunks. |

## External dependencies

| Dependency | Use |
|------------|-----|
| `sqlite3` (stdlib) | The only DB driver; `check_same_thread=False`, `row_factory=sqlite3.Row` |
| `sqlite-vec` (`sqlite_vec`) | Loadable extension providing `vec_distance_cosine()` and `serialize_float32()`. No type stubs — hence `# type: ignore[import-untyped]` on every import |
| SQLite FTS5 (built-in) | The `chunks_fts` keyword index and `bm25()` ranking |
| SQLite JSON1 (`json_each`) | Tag-id membership filtering and tag facet counts |
| `structlog` | Structured logging in `migrations.py`, `_lookups.py`, `writer.py`, `_reembed_guard.py` |
| `common.config.Settings` | `INDEX_DB_PATH`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` |
| `common.clock.utc_now_iso` | The `indexed_at` timestamp |

## Related

- Modules: [indexer](indexer.md) (the sole writer), [search-api](search-api.md) (constructs the `StoreReader`), [search-pipeline](search-pipeline.md) (queries it), [common](common.md) (config + clock)
