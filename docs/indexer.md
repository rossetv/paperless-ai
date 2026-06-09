# The Indexer Daemon

`src/indexer/` is the write side of the semantic-search subsystem. Its job is to keep the search index (`src/store/`) in sync with Paperless-ngx: chunk new and changed documents, embed the chunks, upsert them into the store, and prune documents that have been deleted from Paperless.

**Entry point:** `indexer.daemon:main` (CLI command: `paperless-indexer-daemon`)

The indexer is the **sole writer** to the store — an invariant enforced by an OS-level file lock, not a convention. It also writes a best-effort heartbeat and a per-cycle activity record to the application database (`app.db`) so the web UI's Index dashboard can show what it is doing; if `app.db` is unreachable the indexer still runs, only the dashboard tile goes stale.

The package is split one concept per file (`CODE_GUIDELINES.md` §3.1/§3.3): the daemon entry point is the `indexer.daemon` package (`_boot`, `_loop`, `_wait`), and the reconciliation engine is the `indexer.reconciler` package (`_incremental`, `_light_diff`, `_fanout`, `_failed_documents`, `_sweep`, `_reconciler`).

---

## Architecture Diagram

```
paperless-indexer-daemon  (indexer.daemon)
├── current_settings()                          ← app.db config layered over env
├── acquire_writer_lock(<INDEX_DB_PATH>.lock)   ← fails fast if already held
├── open app.db (best-effort)                   ← dashboard heartbeat + activity
├── SIGTERM / SIGINT handlers
├── Preflight
│   ├── PaperlessClient.ping()
│   └── EmbeddingClient.embed(["ping"])
├── StoreWriter(settings)                        ← runs migrations on construction
├── StoreWriter.check_embedding_model()          ← may trigger a full rebuild
├── Reconciler(settings, paperless, store_writer, embedding_client)
└── _run_loop  (per cycle)
    ├── current_settings() re-check              ← config change rebuilds clients
    ├── consume reconcile.request sentinel       ← forces a deletion sweep
    ├── consume rebuild.request sentinel         ← wipes the index, then re-indexes
    ├── incremental_sync()                        [every cycle]
    ├── deletion_sweep()                          [every DELETION_SWEEP_INTERVAL, or on manual trigger]
    ├── store_writer.checkpoint()                 ← PRAGMA optimize + WAL truncate
    └── _interruptible_wait(RECONCILE_INTERVAL)   ← wakes early on shutdown or a new sentinel
```

---

## Single-Writer Guard (`indexer/lock.py`)

Before doing anything else, the daemon calls `acquire_writer_lock(INDEX_DB_PATH)`. This opens `<INDEX_DB_PATH>.lock` and takes a non-blocking exclusive `flock` (`LOCK_EX | LOCK_NB`). If another indexer process already holds the lock, `flock` raises `BlockingIOError` immediately (surfaced as `IndexerLockError`); the daemon logs `CRITICAL` and exits with code 1. The file handle is kept open for the entire process lifetime — closing it releases the lock.

This is a structural control. The search server reaches the store only through `StoreReader`, which has no write methods. Together they guarantee the single-writer invariant without relying on any database-level coordination.

---

## Preflight

After acquiring the lock, the daemon registers signal handlers, constructs the long-lived `PaperlessClient` and `EmbeddingClient` **once** (so preflight verifies the exact instances the daemon goes on to use), and runs preflight:

1. `PaperlessClient.ping()` — verifies Paperless is reachable. A failure exits code 2.
2. `EmbeddingClient.embed(["ping"])` — verifies the embedding model responds. A failure exits code 2.
3. `StoreWriter(settings)` then `StoreWriter.check_embedding_model()` — compares the configured `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` against `meta`. On a mismatch (or first run) all chunks are wiped and the `modified_watermark` is cleared, triggering a full re-embed on the next cycle (see [Embedding-model change](store.md#embedding-model-change-rebuild)). A `StoreError` here exits code 3.

Any fatal condition logs `CRITICAL` with the traceback and exits non-zero. The daemon never silently starts with a bad configuration.

---

## Configuration Hot-Reload

Configuration is loaded from `app.db`'s `config` table layered over the environment (via `common.config.current_settings`). At the top of every cycle the loop re-checks it: when `config_version` has moved, `_rebuild_reconciler` re-applies logging and library setup (so a changed OpenAI key or base URL takes effect), resizes the LLM concurrency limiter, and rebuilds the Paperless and embedding clients from the new settings — closing the old clients explicitly first. The `StoreWriter` is **not** rebuilt: the index database path is a bootstrap-only env var, so the same writer is carried across. The result is that an operator's config change from the Settings screen propagates with no restart.

---

## Reconciliation Loop (`indexer/daemon/_loop.py`)

The loop is sequential — cycles never overlap. The next cycle begins `RECONCILE_INTERVAL` seconds (default 300) after the previous one *finishes*. State is threaded between iterations as an immutable `_LoopState` (the current reconciler, settings, and the monotonic time of the last completed sweep).

Each iteration:

1. Re-check `current_settings()` — rebuild the reconciler if config changed.
2. Consume the `reconcile.request` sentinel if present (forces a sweep this cycle).
3. Consume the `rebuild.request` sentinel if present.
4. If a rebuild was requested, wipe the index via `StoreWriter.rebuild_index()` (logged, and recorded for the dashboard; a `StoreError` is logged and swallowed so a failed wipe never crashes the daemon — the cycle's normal sync then runs as an ordinary incremental sync).
5. Run `reconciler.incremental_sync()`.
6. Run `reconciler.deletion_sweep()` if the sweep interval has elapsed *or* a manual trigger was pending at cycle start.
7. `store_writer.checkpoint()` — `PRAGMA optimize` then a WAL `TRUNCATE` checkpoint.
8. `_interruptible_wait(RECONCILE_INTERVAL)` — sleeps in short slices, waking early on shutdown or a new sentinel, and beating the dashboard heartbeat periodically so the indexer is not reported as "stopped" while merely idle.

Steps 4–7 run inside a cycle-level `except Exception` (the documented outer-boundary catch) that logs the traceback with `log.exception(...)` and falls through to the wait. A failed cycle never crashes the daemon and never advances the deletion-sweep clock (`last_sweep_at` is assigned only after a sweep completes, so a missed sweep is retried next cycle).

---

## Incremental Sync (`indexer/reconciler/_incremental.py`)

### Watermark-driven paging, two paths

1. Read `meta.modified_watermark` from the store.
2. Refresh the taxonomy once (see below), before any document work, so a rename is reflected even on a cycle that indexes nothing.
3. Read the index state — `id → (modified, content_hash)` for every document. This is cheap (no OCR bodies) and is shared by every batch's worker fan-out.
4. Page the watermark window. **The page stream is never materialised whole** — `iter_all_documents` is a lazy generator at `page_size=100`, and on a first-run backfill that is the entire archive. The sync consumes it in fixed-size batches of 100; each batch is indexed and then dropped so its OCR bodies are freed before the next page is fetched. Peak memory is O(one batch), not O(whole archive).

Which fields are paged depends on whether this is a backfill or steady state:

- **First-run backfill** (`modified_watermark` is `None` → no server-side filter): every document is new, so its OCR body is needed anyway. Page **full** documents and stream them in batches.
- **Steady state** (a watermark exists): page a **light `{id, modified}` projection** (`fields=("id", "modified")`, so Paperless transfers no OCR content), diff each row against the store, and fetch the full document only for the genuinely-changed ones (see [Light diff](#steady-state-light-diff) below).

5. After the page is consumed, advance `modified_watermark` to `(max modified seen) − OVERLAP_MARGIN` (10 seconds), but **only if the page held at least one document**. The small overlap absorbs timestamp-boundary races; the content-hash gate makes re-processing the overlap free. Only the watermark-page documents feed that maximum — out-of-band retries (below) do not.

The watermark advances **unconditionally on the failure count**. Failures are tracked and retried via the persisted `failed_documents` map rather than by freezing the watermark, so one poison document can neither stall forward progress nor force the changed tail to be re-paged forever.

### Steady-state light diff (`indexer/reconciler/_light_diff.py`)

The classifier daemon `PATCH`es metadata constantly (titles, tags), which bumps Paperless's `modified` and pulls those documents back into the watermark window every cycle — but their OCR content is unchanged. The light diff skips them without paying to transfer the body:

- For each `{id, modified}` row, fold its `modified` into the running watermark maximum (so the watermark advances past skipped documents too), then compare its **normalised** `modified` against the stored `IndexState.modified`.
- If the document already has a store row and the normalised `modified` is unchanged → **skip**: no OCR body is fetched, no store write happens.
- Otherwise (new id, or `modified` advanced) → fetch the full document via `get_document` and run it through the worker, whose SHA-256 hash gate decides metadata-only vs re-embed.

The skip is **fail-safe by construction**: two different `modified` instants cannot normalise to the same string, so a genuinely-changed document is never skipped; a normalisation that fails to match merely costs a redundant full fetch — exactly the old behaviour — never a wrong skip. The hash gate is therefore never bypassed for any document whose content reaches the store.

### The shared `modified` fold (`_fold_modified`)

Both paths compute the watermark's maximum the same way, via one shared fold in `_light_diff.py`:

```python
def _fold_modified(latest, raw, document_id) -> datetime | None
```

It parses one raw `modified` string and returns the new running maximum. An absent or empty value leaves `latest` unchanged; an unparseable value is logged at `WARNING` and skipped, so a malformed upstream timestamp never aborts the watermark advance. The batch full-document path (`_fold_latest_modified`) and the per-row steady-state diff (`_diff_light_page`) both call it, so the watermark maximum is computed identically and without ever holding more than one batch in memory.

### Per-document worker (`indexer/worker.py`)

`DocumentIndexer` is stateless and shared across the worker pool. For each document:

1. **Gate** — skip if `content` is empty/whitespace (OCR has not run yet) or `ERROR_TAG_ID` is present on the document. A document that was *previously* indexed but has now become un-indexable is **pruned** from the store in this step (otherwise search would keep serving chunks for content that no longer exists, and the deletion sweep can't reach it because the document still exists in Paperless). Both branches return `SKIPPED`; the log event distinguishes them (`worker.stale_document_pruned` vs `worker.document_skipped`).
2. **Hash** — compute SHA-256 of the OCR content.
3. **Hash gate:**
   - *Hash unchanged* (e.g. the classifier updated a title or tag, but the text is identical): call `StoreWriter.update_metadata` — refresh title, `correspondent_id`, `document_type_id`, `tag_ids`, `modified`. **No re-chunking, no re-embedding.**
   - *Hash changed or new document*: full path — chunk → embed → `upsert_document`.
4. **Chunk** (`indexer/chunker.py`) — paragraph-aware ~`CHUNK_SIZE`-character windows (default 2000) with `CHUNK_OVERLAP` overlap (default 256). Page hints are parsed from the OCR page markers (`--- Page N ---`, optionally `--- Page N (model-name) ---`) that the **OCR daemon** writes into the assembled text (`ocr.text_assembly`). Chunking is character-based, not token-based; a defensive 6000-character ceiling is enforced after paragraph-aware chunking so no single chunk can blow past `text-embedding-3-small`'s 8191-token input limit even for dense non-Latin OCR.
5. **Embed** — `EmbeddingClient.embed(texts)` batches the document's chunks into API-sized requests.
6. **Upsert** — `StoreWriter.upsert_document(meta, chunks)`, one atomic transaction.

The entire upsert is one transaction: delete the document's old chunks from `chunks` and `chunks_fts`, insert the new chunks, write the `documents` row. A crash mid-upsert leaves the previous version fully intact.

### Worker-pool fan-out (`indexer/reconciler/_fanout.py`)

One `ThreadPoolExecutor` (named `indexer-document`, `DOCUMENT_WORKERS` threads, default 4) is constructed **per cycle** and reused across every batch and the retry pass — not one pool per 100-document batch, which on a backfill of N documents would spin up `ceil(N/100)` pools and fragment the thread-name numbering. Each document is dispatched through `_index_one`, which catches and isolates that document's failure (the documented per-worker outer-boundary catch): a raise is logged with its traceback, recorded as a `None` outcome, and the batch continues.

### Failed-document retry and dead-letter (`indexer/reconciler/_failed_documents.py`)

The failed-document map is a JSON object in store meta mapping `str(doc_id) → consecutive_failure_count`. Forward progress (the watermark) is decoupled from failure retry:

- On each cycle, every id in the map that the watermark page did **not** already cover is re-attempted out-of-band: it is fetched fresh and indexed through the same pool. An id confirmed gone from Paperless (via `document_exists`) is dropped from the map (the deletion sweep removes it from the store). A transport error re-fetching one id is isolated — the id keeps its count and is retried next cycle.
- After indexing, the map is rebuilt from the cycle's outcomes: a document that succeeded is cleared; a document that failed has its count incremented.
- After `MAX_CONSECUTIVE_DOCUMENT_FAILURES` (5) consecutive failures, the document is **dead-lettered**: logged at `CRITICAL`, dropped from the map, and not re-attempted until Paperless modifies it again (which advances its `modified` back into the watermark window). This bounds the per-document retry cost so one poison document cannot consume embedding budget indefinitely.

### `SyncReport`

The `SyncReport` returned per cycle counts both the watermark page and the out-of-band retries:

| Field | Meaning |
|:---|:---|
| `indexed` | Documents fully chunked, embedded, and upserted |
| `metadata_only` | Documents whose hash was unchanged — metadata updated, no re-embed |
| `skipped` | Documents gated out (empty content or error tag), including stale-prunes |
| `failed` | Documents that raised this cycle (isolated and counted) |
| `given_up` | Documents dead-lettered this cycle (a subset of `failed`) |

`last_reconcile_at` is written at the end of **every** completed cycle — including cycles where Paperless returned zero documents — because an empty-but-reconciled index is genuinely ready to serve. Without this the search server's healthz check would return `503 index-not-ready` forever.

---

## Taxonomy Refresh

Every cycle, before processing documents, the reconciler fetches the complete correspondent, document-type, and tag lists from Paperless and calls `StoreWriter.refresh_taxonomy(entries)`, which atomically replaces the entire `taxonomy` table (DELETE all, INSERT new). A malformed upstream row (missing `id` or `name`) is skipped with a warning rather than persisted.

A correspondent or tag rename in Paperless therefore takes effect immediately for all search and facet queries — zero document rewrites required.

---

## Deletion Sweep (`indexer/reconciler/_sweep.py`)

Inferring deletion from absence is a data-loss footgun if the enumeration is incomplete. The sweep is therefore conservative:

1. Every `DELETION_SWEEP_INTERVAL` seconds (default 3600), enumerate **all** Paperless document ids by paging the full list endpoint with `fields=("id",)` — the sweep needs only the id set, so every other field (notably the OCR body) is projected away.
2. If *any* page raises during enumeration, **abort the sweep and prune nothing** — a partial list is never authoritative, because treating it as such would delete every not-yet-seen document the moment Paperless blips mid-pagination. An aborted sweep sets `SweepReport.aborted = True` and logs a warning.
3. On a verified-complete enumeration, compute `store_ids − paperless_ids`.
4. For each candidate id, confirm it is gone with a second `document_exists` check before pruning — guarding against a create-during-enumeration race. A confirmation that itself raises conservatively *keeps* the document.
5. Prune the confirmed-absent set with `StoreWriter.delete_documents`, then record `last_full_sweep_at`.

A `SweepReport` is returned:

| Field | Meaning |
|:---|:---|
| `pruned` | Documents removed from the store |
| `candidates` | Documents in the store but not in Paperless's id set (zero when aborted) |
| `aborted` | True if the enumeration failed |

---

## Manual Triggers

Both triggers reach the indexer through a **sentinel file** on the shared `/data` volume, not a store write or a new network port — because the indexer and the search server are separate processes and the indexer is the sole store writer.

**Reconcile now.** `POST /api/reconcile` (Member or above) touches `<data-dir>/reconcile.request` and returns `202 Accepted`. The indexer's `_interruptible_wait` detects it on its next slice, deletes it, and starts the next cycle immediately — including a deletion sweep regardless of the sweep interval. Multiple requests during one running cycle coalesce into a single follow-up cycle. The caller tracks completion by polling `GET /api/stats` (or the Index dashboard) for an advancing `last_reconcile_at`.

**Rebuild index.** `POST /api/index/rebuild` (Admin only) touches `<data-dir>/rebuild.request`. The indexer consumes it at cycle entry, wipes the index via `StoreWriter.rebuild_index()`, and the same cycle's incremental sync re-indexes the whole archive (watermark cleared → no server-side filter).

---

## Concurrency Model

```
indexer process
├── Main thread (reconciliation loop — sequential)
│   └── ThreadPoolExecutor("indexer-document", DOCUMENT_WORKERS threads) — one per cycle
│       ├── document A → gate → hash → chunk → embed → upsert (StoreWriter, serialised via _write_lock)
│       ├── document B → gate → hash → chunk → embed → upsert
│       └── ...
└── EmbeddingClient → ConcurrencyGuard(EMBEDDING_MAX_CONCURRENT) bounds concurrent embedding API calls
```

Embedding is the network bottleneck on a large backfill. The `EmbeddingClient` owns a `ConcurrencyGuard` sized by `EMBEDDING_MAX_CONCURRENT` (default 4) which, plus the `@retry` decorator's exponential backoff with jitter, turns API rate-limit errors into steady throughput rather than a retry storm. The `StoreWriter` holds an internal `threading.Lock` around each write transaction, so concurrent workers share one writer safely while their embedding work runs in parallel.

---

## Graceful Shutdown

SIGTERM or SIGINT sets a thread-safe shutdown flag (via `common/shutdown.py`). The main loop checks the flag at the top of each cycle and inside `_interruptible_wait`. In-flight embedding calls and the current upsert transaction complete normally before the daemon exits; the per-cycle worker pool's `with` block joins its in-flight threads on the way out. The per-document upsert transaction guarantees a clean interrupt boundary — there is no half-indexed document state.

---

## File Index

| File | Purpose |
|:---|:---|
| `daemon/_boot.py` | Flock, preflight, client construction, dashboard wiring, loop entry |
| `daemon/_loop.py` | The reconciliation run-loop, per-cycle body, config hot-reload, rebuild handling |
| `daemon/_wait.py` | `_interruptible_wait`, sentinel consumption, idle heartbeat |
| `reconciler/_incremental.py` | Watermark-driven sync, taxonomy refresh, batched streaming, watermark advance |
| `reconciler/_light_diff.py` | Steady-state `{id, modified}` diff and the shared `_fold_modified` fold |
| `reconciler/_fanout.py` | Per-cycle worker-pool dispatch with per-document failure isolation |
| `reconciler/_failed_documents.py` | Bounded failed-document retry and dead-lettering |
| `reconciler/_sweep.py` | The deletion sweep with its "a partial enumeration prunes nothing" rule |
| `reconciler/_reconciler.py` | `Reconciler` facade — `incremental_sync` and `deletion_sweep` |
| `worker.py` | `DocumentIndexer` — per-document gate, hash gate, chunk, embed, upsert, stale-prune |
| `chunker.py` | Paragraph-aware text chunker with OCR page-marker hints |
| `lock.py` | `acquire_writer_lock` — OS flock on `<INDEX_DB_PATH>.lock` |
| `activity.py` | `IndexerActivityRecorder` — dashboard heartbeat and reconcile-activity rows |
