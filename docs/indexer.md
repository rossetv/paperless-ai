# The Indexer Daemon

`src/indexer/` is the write side of the semantic-search subsystem. Its sole job is to keep the search index (`src/store/`) in sync with Paperless-ngx: chunk new and changed documents, embed the chunks, upsert them into the store, and prune documents that have been deleted from Paperless.

**Entry point:** `indexer.daemon:main` (CLI command: `paperless-indexer-daemon`)

The indexer is the **sole writer** to the store. This is an invariant enforced by an OS-level file lock, not a convention.

---

## Architecture Diagram

```
paperless-indexer-daemon
├── acquire_writer_lock(<INDEX_DB_PATH>.lock)   ← fails fast if already held
├── SIGTERM / SIGINT handlers
├── Preflight
│   ├── PaperlessClient.ping()
│   └── EmbeddingClient.embed(["ping"])
├── StoreWriter(settings)  ← runs migrations on construction
├── StoreWriter.check_embedding_model()  ← may trigger a full rebuild
├── Reconciler(settings, paperless, store_writer, embedding_client)
└── _run_loop
    ├── incremental_sync()  [every cycle]
    ├── deletion_sweep()    [every DELETION_SWEEP_INTERVAL, or on manual trigger]
    ├── store_writer.checkpoint()
    └── _interruptible_wait(RECONCILE_INTERVAL)
           ↑ wakes early on SIGTERM or reconcile.request sentinel
```

---

## Single-Writer Guard (`indexer/lock.py`)

Before doing anything else, the daemon calls `acquire_writer_lock(INDEX_DB_PATH)`. This opens `<INDEX_DB_PATH>.lock` and takes a non-blocking exclusive `flock` (`LOCK_EX | LOCK_NB`). If another indexer process is already running and holds the lock, `flock` raises `BlockingIOError` immediately; the daemon logs `CRITICAL` and exits with code 1. The file handle is kept open for the entire process lifetime — closing it releases the lock.

This is a structural control. The search server reaches the store only through `StoreReader`, which has no write methods. Together they guarantee the single-writer invariant without relying on any database-level coordination.

---

## Preflight

After acquiring the lock, the daemon registers signal handlers and runs preflight checks:

1. `PaperlessClient.ping()` — verifies Paperless is reachable.
2. `EmbeddingClient.embed(["ping"])` — verifies the embedding model responds.
3. `StoreWriter.check_embedding_model()` — compares the configured `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS` against `meta`. On a mismatch (or first run), all chunks are wiped and the `modified_watermark` is cleared, triggering a full re-embed on the next cycle (see [Embedding-model change](store.md#embedding-model-change-rebuild)).

Any fatal condition during preflight logs `CRITICAL` and exits non-zero. The daemon never silently starts with a bad configuration.

---

## Reconciliation Loop (`indexer/daemon.py`)

The reconciliation loop is sequential — cycles never overlap. The next cycle begins `RECONCILE_INTERVAL` seconds after the previous one *finishes*.

Each iteration:

1. Check the shutdown flag — exit immediately if set.
2. Consume the manual-trigger sentinel file if present.
3. Run `reconciler.incremental_sync()`.
4. Run `reconciler.deletion_sweep()` if the sweep interval has elapsed or a manual trigger was pending.
5. `store_writer.checkpoint()` — WAL checkpoint so the search server never chases an unbounded WAL file.
6. `_interruptible_wait(RECONCILE_INTERVAL)` — sleeps in 5-second slices, waking early on SIGTERM or a new sentinel file.

A cycle-level `except Exception` catches any transient failure (a taxonomy-refresh network error, a malformed Paperless document, a `StoreError`), logs the traceback with `log.exception(...)`, and falls through to the wait. A failed cycle never crashes the daemon and never advances the deletion-sweep clock.

---

## Incremental Sync (`indexer/reconciler.py`)

### Watermark-driven paging

1. Read `meta.modified_watermark` from the store (epoch on first run, which makes the initial backfill identical to a normal incremental sync — no special path).
2. Page `GET /api/documents/?modified__gt=<watermark>&ordering=modified` via `PaperlessClient.iter_all_documents(modified_after=...)`. This is **real server-side filtering** — steady-state cycles transfer only the changed tail, not the whole archive.
3. Fan changed documents across a `ThreadPoolExecutor` (`DOCUMENT_WORKERS` threads, named `indexer-document`).
4. After a batch page completes, advance `modified_watermark` to `(max modified seen) − OVERLAP_MARGIN` (10 seconds). The small overlap absorbs timestamp-boundary races; the content-hash gate makes re-processing the overlap free.

### Per-document worker (`indexer/worker.py`)

For each document in the page:

1. **Gate** — skip if `content` is empty (OCR has not run yet) or `ERROR_TAG_ID` is present on the document.
2. **Hash** — compute SHA-256 of the OCR content.
3. **Hash gate:**
   - *Hash unchanged* (e.g. the classifier updated a title or tag, but text is identical): call `StoreWriter.update_metadata`. Refresh title, `correspondent_id`, `document_type_id`, `tag_ids`, `modified`. **No re-chunking, no re-embedding.**
   - *Hash changed or new document*: full path — chunk → embed → `upsert_document`.
4. **Chunk** (`indexer/chunker.py`) — paragraph-aware ~`CHUNK_SIZE`-character windows with `CHUNK_OVERLAP` overlap. Page hints are parsed from OCR page markers where present (the classifier daemon writes `--- Page N ---` headers). Character-based, not token-based; 2000 characters is well under `text-embedding-3-small`'s 8191-token input limit.
5. **Embed** — `EmbeddingClient.embed(texts)` batches the document's chunks into API-sized requests.
6. **Upsert** — `StoreWriter.upsert_document(meta, chunks)`, one atomic transaction.

The entire upsert is one transaction: delete the document's old chunks from `chunks` and `chunks_fts`, insert the new chunks, update the `documents` row. A crash mid-upsert leaves the previous version fully intact.

### Failed-document retry and dead-letter mechanism

A per-document failure is logged and isolated — the cycle continues. The failed document id is recorded in `meta.failed_documents` (a JSON object mapping `str(doc_id) → consecutive_failure_count`). On each subsequent cycle, failed documents are re-attempted out-of-band (independent of whether the watermark sweep re-fetches them).

After `MAX_DOCUMENT_FAILURES` (5) consecutive failures, the document is **dead-lettered**: logged at `CRITICAL`, removed from the retry map, and not re-attempted until Paperless modifies it again (which would advance its `modified` timestamp back into the watermark sweep). This prevents one poison document from stalling forward progress or consuming embedding budget indefinitely.

The `SyncReport` returned per cycle counts:

| Field | Meaning |
|:---|:---|
| `indexed` | Documents fully chunked, embedded, and upserted |
| `metadata_only` | Documents updated without re-embedding |
| `skipped` | Documents gated out (empty content or error tag) |
| `failed` | Documents that raised this cycle |
| `given_up` | Documents dead-lettered this cycle (subset of `failed`) |

---

## Taxonomy Refresh

Every cycle, before processing documents, the reconciler fetches the complete correspondent, document-type, and tag lists from Paperless and calls `StoreWriter.refresh_taxonomy(entries)`. This atomically replaces the entire `taxonomy` table (DELETE all, INSERT new).

A correspondent or tag rename in Paperless therefore takes effect immediately for all search and facet queries — zero document rewrites required.

---

## Deletion Sweep (`indexer/reconciler.py`)

Inferring deletion from absence is a data-loss footgun if the enumeration is incomplete. The sweep is therefore conservative:

1. Every `DELETION_SWEEP_INTERVAL` seconds (default 3600), enumerate **all** Paperless document ids by paging the full list endpoint.
2. If *any* page raises during enumeration, **abort the sweep and prune nothing** — a partial list is never treated as authoritative. An aborted sweep sets `SweepReport.aborted = True` and logs a warning.
3. On a verified-complete enumeration, compute `store_ids − paperless_ids`.
4. For each candidate id, confirm with `GET /api/documents/{id}/` returning 404 before calling `delete_documents`. This 404 confirmation prevents false pruning from a transient Paperless outage mid-enumeration.

A `SweepReport` is returned:

| Field | Meaning |
|:---|:---|
| `pruned` | Documents removed from the store |
| `candidates` | Documents that were in the store but not in Paperless's id set |
| `aborted` | True if the enumeration failed |

---

## Manual Reconciliation Trigger

The search server exposes `POST /api/reconcile` (see [Search](search.md)). Because the indexer and the search server are separate processes, and the indexer is the sole store writer, the trigger is passed through a **sentinel file** on the shared `/data` volume rather than a store write or a new network port.

- `POST /api/reconcile` writes (touches) `<directory of INDEX_DB_PATH>/reconcile.request` and returns `202 Accepted`.
- The indexer's `_interruptible_wait` polls for the sentinel in 5-second slices. When it detects the file it deletes it and returns early, starting the next cycle immediately — including a deletion sweep, regardless of the sweep interval.
- Multiple requests arriving during one running cycle coalesce: only one follow-up cycle runs.
- The caller tracks completion by polling `GET /api/stats` for an advancing `last_reconcile_at`.

---

## Concurrency Model

```
indexer process
├── Main thread (reconciliation loop — sequential)
│   └── ThreadPoolExecutor("indexer-document", DOCUMENT_WORKERS threads)
│       ├── document A → hash → chunk → embed → upsert (StoreWriter, serialised via _write_lock)
│       ├── document B → hash → chunk → embed → upsert
│       └── ...
└── EMBEDDING_MAX_CONCURRENT semaphore — bounds concurrent embedding API calls
```

Embedding is the network bottleneck on a large backfill. The `EMBEDDING_MAX_CONCURRENT` semaphore (default 4) plus the `@retry` decorator's exponential backoff turn API rate-limit errors into steady throughput rather than a retry storm.

The `StoreWriter` holds an internal `threading.Lock` around each write transaction, so concurrent workers share one writer safely.

---

## Graceful Shutdown

SIGTERM or SIGINT sets a thread-safe shutdown flag (via `common/shutdown.py`). The main loop checks the flag at the top of each cycle and inside `_interruptible_wait`. In-flight embedding calls and the current upsert transaction complete normally before the daemon exits. The per-document upsert transaction guarantees a clean interrupt boundary — there is no half-indexed document state.

---

## File Index

| File | Purpose |
|:---|:---|
| `daemon.py` | Entry point — lock, preflight, reconciliation loop |
| `reconciler.py` | `Reconciler` — incremental sync, deletion sweep, taxonomy refresh |
| `worker.py` | `DocumentIndexer` — per-document hash gate, chunk, embed, upsert |
| `chunker.py` | Paragraph-aware text chunker |
| `lock.py` | `acquire_writer_lock` — OS flock on `<INDEX_DB_PATH>.lock` |
