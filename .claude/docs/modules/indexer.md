<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: indexer

## Purpose

The write side of the semantic-search subsystem: a long-running daemon that reconciles Paperless-ngx against the SQLite search index (`index.db`). It is the **only** process that writes the index — `store.writer.StoreWriter` is referenced nowhere outside `src/indexer/` and `src/store/`. Each cycle it re-checks hot-loaded config, consumes trigger sentinels, refreshes the taxonomy, pages Paperless for documents modified since a persisted watermark, chunks + embeds + upserts the changed ones through a thread pool, periodically sweeps documents deleted from Paperless, checkpoints the WAL, and sleeps.

Package contract (`src/indexer/__init__.py`): allowed — `store/` (write API) and `common/`; forbidden — `search/` imports, FastAPI, direct `sqlite3` usage. The `daemon`, `reconciler`, and `worker` module docstrings extend the forbidden list with direct `httpx` / bare `openai` calls.

**Entrypoint:** `src/indexer/daemon/_boot.py::main`, re-exported as `indexer.daemon:main` and wired to the console script via the `paperless-indexer-daemon = "indexer.daemon:main"` entry in `[project.scripts]` (`pyproject.toml`).

Boot order: `current_settings()` → `configure_logging`/`setup_libraries` → `acquire_writer_lock(INDEX_DB_PATH)` (exit **1** if contended) → best-effort open `app.db` → `register_signal_handlers` → preflight (`paperless.ping` + `embedding_client.embed(["ping"])`, exit **2** on failure) → `StoreWriter` + `check_embedding_model()` (exit **3** on `StoreError`) → build `Reconciler` → `_run_loop`.

## Key files

| File | Role |
|------|------|
| `src/indexer/daemon/_boot.py` | Boot sequence and process entrypoint (`main`, `_start_daemon`, `_run_preflight`, `_open_app_db`). Owns the flock lifetime, the exit codes, and the long-lived `PaperlessClient`/`EmbeddingClient` that preflight itself exercises, plus the `StoreWriter` whose `check_embedding_model()` is the store-side preflight. Derives `sentinel_path = Path(INDEX_DB_PATH).parent / "reconcile.request"`. |
| `src/indexer/daemon/_loop.py` | The run-loop and cycle body. `_run_loop` drives `_run_one_cycle` then `_interruptible_wait`. `_run_one_cycle` does the config re-check and sentinel consumption (`reconcile.request` + `rebuild.request`) *before* the `try`, then runs rebuild → `incremental_sync` → due-when `deletion_sweep` → `checkpoint` inside one `try/except Exception` fault-isolation boundary. `_rebuild_reconciler` rebuilds config-derived clients on a config bump; `_run_rebuild` wipes the index on a rebuild sentinel. State is a frozen `_LoopState(reconciler, settings, last_sweep_at)`. |
| `src/indexer/daemon/_wait.py` | Inter-cycle wait (`_interruptible_wait`, `_WAKE_CHECK_INTERVAL` 5 s slices, `_IDLE_BEAT_INTERVAL` idle heartbeat every 30 s) and `_consume_sentinel` (exists → unlink → `True`). Pure leaf module. |
| `src/indexer/reconciler/_reconciler.py` | `Reconciler` facade — owns settings/paperless/store_writer/embedding_client and one shared `DocumentIndexer`; exposes `incremental_sync()`, `deletion_sweep()`, and the `paperless`/`embedding_client`/`store_writer` properties the hot-reload close-and-rebuild needs. |
| `src/indexer/reconciler/_incremental.py` | `run_incremental_sync` — the core. Reads `modified_watermark`, refreshes the taxonomy, reads `get_index_state()` once, builds ONE `ThreadPoolExecutor` per cycle, branches on watermark `None` (full-document backfill via `_index_page_stream`) vs steady state (light diff), runs the out-of-band failed-document retry pass, advances the watermark, tallies a `SyncReport`, writes `last_reconcile_at`. Defines `OVERLAP_MARGIN` (10 s), `_WATERMARK_PAGE_BATCH_SIZE` (100), and the 3.11-compatible `_batched`. |
| `src/indexer/reconciler/_light_diff.py` | IDX-03 steady-state optimisation. Pages a sparse `_LIGHT_DIFF_FIELDS = ("id", "modified")` Paperless projection, skips rows whose normalised `modified` equals the stored `IndexState.modified` (no OCR body fetched), fetches only genuinely-changed ids in full (per-id fetch failure isolated as a `None` outcome). Owns `_fold_modified`, the single running-max implementation shared with `_incremental`. |
| `src/indexer/reconciler/_fanout.py` | Leaf module owning worker-pool dispatch: `_index_documents` (`pool.map` over a `functools.partial`) and `_index_one`, which catches every exception per document, logs it, and returns `(id, None)`. Imported downward by both `_incremental` and `_light_diff` — this is what breaks the import cycle. Does **not** own the pool. |
| `src/indexer/reconciler/_failed_documents.py` | Bounded retry + dead-lettering (SPEC §5.7). Owns the persisted `failed_documents` meta map (JSON `str(id) -> consecutive_failure_count`), `MAX_CONSECUTIVE_DOCUMENT_FAILURES = 5`, `read_failed_documents` (corrupt value → `{}` + warning), `fetch_retry_documents` (a `document_exists` probe drops Paperless-deleted ids in place), `update_failed_documents` (success clears, failure increments, 5th failure logs CRITICAL and dead-letters). |
| `src/indexer/reconciler/_sweep.py` | `run_deletion_sweep` (SPEC §5.4). Enumerates all Paperless ids with `fields=("id",)`; ANY enumeration failure → `None` → `SweepReport(pruned=0, aborted=True, candidates=0)` and prunes nothing. Otherwise `store_ids - paperless_ids`, each candidate 404-confirmed via `document_exists`, `delete_documents(prune_set)`, write `last_full_sweep_at`. |
| `src/indexer/worker.py` | `DocumentIndexer` — the stateless, thread-safe per-document pipeline (SPEC §5.3): gate (empty/whitespace content or `ERROR_TAG_ID` → `SKIPPED`, pruning any existing row), SHA-256 hash, hash gate (unchanged → `update_metadata` → `METADATA_ONLY`), else chunk + embed + `upsert_document` → `INDEXED`. Zero-chunk guard (IDX-M1). `IndexOutcome` lives here; `_build_meta` normalises created/modified to UTC ISO-8601. |
| `src/indexer/chunker.py` | `chunk_text` — paragraph-aware character windowing with overlap, plus `page_hint` extraction from `--- Page N ---` / `--- Page N (model) ---` OCR markers (`_PAGE_MARKER_RE`). Three passes: parse lines → paragraphs, assemble overlapping windows (`_assemble_chunks`), enforce the defensive `_MAX_CHUNK_CHARS = 6000` ceiling (`_cap_chunk_sizes`, IDX-02). Defines the frozen `TextChunk`. |
| `src/indexer/activity.py` | `IndexerActivityRecorder` — writes `reconcile_activity` rows and beats the `indexer` `daemon_status` heartbeat in `app.db` for the Index dashboard (`record_sync` / `record_sweep` / `record_rebuild` / `beat_idle`). Every write is best-effort: `sqlite3.Error` and `OSError` are swallowed with a warning. |
| `src/indexer/lock.py` | `acquire_writer_lock` — non-blocking exclusive `fcntl.flock` on `<INDEX_DB_PATH>.lock`; `BlockingIOError` → `IndexerLockError`. Caller holds the handle for the process lifetime. Stdlib only. |
| `src/indexer/reconciler/__init__.py` | Public surface: `Reconciler`, `SyncReport`, `SweepReport`, `OVERLAP_MARGIN`, `MAX_CONSECUTIVE_DOCUMENT_FAILURES`. |
| `tests/unit/indexer/conftest.py` | Shared fixtures: autouse shutdown-flag reset, `make_reconciler_store_writer` (MagicMock with a working in-memory meta dict exposed as `_meta`), `always_indexed` stub, `run_incremental_sync` helper. Paperless/embedding mocks come from `tests/helpers/mocks`. |
| `tests/unit/indexer/test_daemon.py` | 17 tests over `_run_loop`/`_run_one_cycle`: cycle shape, shutdown, sentinel-forced sweep, cycle fault isolation, sweep cadence via an injected clock, config hot-reload, rebuild sentinel. |
| `tests/unit/indexer/test_daemon_main.py` | 6 tests: `main` exits non-zero on a contended lock / proceeds when acquired, plus the four `_interruptible_wait` cases (shutdown, full duration elapsed, sentinel consumed → `True`, idle heartbeat during a long interval). |
| `tests/unit/indexer/test_lock.py` | 3 tests for `acquire_writer_lock` — acquire, contention → `IndexerLockError`, release. |
| `tests/unit/indexer/test_reconciler_incremental.py` | 24 tests: watermark read/advance, `OVERLAP_MARGIN` re-inclusion → `METADATA_ONLY` no-op, changed-document re-index, per-document failure isolation, mid-pagination failure leaves the watermark unmoved, light-diff steady-state skip. |
| `tests/unit/indexer/test_reconciler_incremental_cycle.py` | 8 tests over the cycle-level shape of `run_incremental_sync`: the taxonomy refresh, the unconditional `last_reconcile_at` write, and the `SyncReport` tallies. |
| `tests/unit/indexer/test_reconciler_sweep.py` | 12 tests for the sweep safety rules — complete enumeration prunes only truly-absent ids; a mid-pagination failure prunes NOTHING; a candidate that still 404-confirms present is kept. |
| `tests/unit/indexer/test_reconciler_failed_documents.py` | 5 tests: the map persists, the out-of-band retry fires, the 5th consecutive failure dead-letters, a Paperless-deleted failed id is dropped. |
| `tests/unit/indexer/test_worker.py` | 31 tests over `DocumentIndexer`: gates, hash gate, re-index, stale prune, zero-chunk guard, date normalisation. |
| `tests/unit/indexer/test_chunker.py` | 34 tests: overlap correctness, paragraph-boundary preference, page-hint extraction, oversize-paragraph slicing, the 6000-char cap, contiguous `chunk_index`, empty input. |
| `tests/unit/indexer/test_activity.py` | 9 tests over `IndexerActivityRecorder`: the recorded rows, the `ok` flag, the heartbeat beat, and the best-effort swallow. |
| `tests/integration/test_indexer_pipeline.py` | 8 tests driving the REAL `Reconciler` + REAL `StoreWriter` against a `tmp_path` SQLite store (only Paperless and the embedding client mocked). |
| `tests/integration/test_indexer_pipeline_sweep.py` | 5 tests: real sweep against a real store, including the mid-pagination-failure case asserting the store is left byte-for-byte intact. |
| `tests/integration/test_reconciler_healthz_seam.py` | 2 tests proving the real `incremental_sync` writes `last_reconcile_at` and the real `StoreReader`-backed healthz then reports ready. |

## Invariants

- **Single writer, enforced by the OS.** `acquire_writer_lock` takes a non-blocking exclusive `fcntl.flock` on `<INDEX_DB_PATH>.lock`; a contended lock is a CRITICAL log and `sys.exit(1)` in `_boot.main`. The handle is held by `main`'s stack frame for the process lifetime.
- **A partial deletion enumeration prunes NOTHING.** `_enumerate_paperless_ids` wraps the whole paged enumeration in one `try`; any `PAPERLESS_CALL_EXCEPTIONS` returns `None` and `run_deletion_sweep` returns `SweepReport(pruned=0, aborted=True, candidates=0)`. Every surviving candidate is then independently 404-confirmed with `document_exists`, and a confirm that itself raises conservatively **keeps** the document (`_confirm_absent`). `last_full_sweep_at` is written only on a verified-complete sweep.
- **The watermark advances unconditionally on the failure count.** Whenever the watermark page held at least one document, `modified_watermark := max(parseable modified seen) - OVERLAP_MARGIN` (10 s). Retry documents never influence the watermark. Failures are decoupled into the persisted `failed_documents` map, so one poison document can neither stall forward progress nor force the changed tail to be re-embedded forever.
- **Per-document failures are isolated, never fatal.** `_index_one` catches every `Exception`, logs it, and returns `(id, None)`; a `None` outcome counts as `failed` and increments that id's consecutive-failure count. At `MAX_CONSECUTIVE_DOCUMENT_FAILURES = 5` the document is logged CRITICAL and dead-lettered (dropped from the map) — retried only when its content next changes.
- **Cycle-level fault isolation.** `_run_one_cycle` wraps rebuild + sync + sweep + checkpoint in `try/except Exception` → `log.exception("indexer.cycle_failed")` and falls through to the wait. `last_sweep_at` is assigned only AFTER a successful sweep, so a failed cycle never advances the sweep clock and a missed sweep is retried next cycle.
- **Peak memory is O(one batch), never O(whole archive).** `iter_all_documents` is a lazy generator whose documents each carry the full OCR body; `_batched` consumes it 100 documents at a time and each batch is dropped after indexing. Materialising the stream would OOM the host on a first-run backfill.
- **`DocumentIndexer` holds no per-document mutable state** — one instance is shared across the whole worker pool for the reconciler's lifetime; all state passes through method arguments.
- **A document that cannot be indexed never gets a `content_hash` stored.** Empty/whitespace content, an `ERROR_TAG_ID` tag, or content that chunks to zero chunks → `IndexOutcome.SKIPPED` with no upsert (IDX-M1: a 0-chunk row with a hash would make the hash gate classify it `METADATA_ONLY` forever and permanently hide it from search). A previously-indexed document that becomes un-indexable has its rows pruned (`delete_documents`) so search stops serving stale chunks.
- **No chunk may exceed 6000 characters.** `_cap_chunk_sizes` hard-splits any chunk over `_MAX_CHUNK_CHARS` after paragraph-aware chunking (IDX-02), so dense CJK/non-Latin OCR cannot blow the embedding model's 8191-token input limit and fail a whole 96-item embedding batch (`common.embeddings._BATCH_SIZE`). No overlap is added between forced sub-splits.
- **The light-diff skip is fail-safe by construction:** two different `modified` instants cannot normalise to the same string, so a genuinely-changed document is never skipped; an unrecognised format merely costs a redundant full fetch. The SHA-256 hash gate is never bypassed for any document whose content reaches the store.
- **Dashboard observability is best-effort and never crashes the indexer:** `app.db` is opened best-effort at boot (`None` → the recorder is simply absent), and `IndexerActivityRecorder._record` swallows `sqlite3.Error`/`OSError` with a warning.
- **`ok=True` on a recorded sync means the cycle completed**, not that every document succeeded (per-document failures are counted in the summary). Only an ABORTED sweep is `ok=False`.
- **The `StoreWriter` is never rebuilt on a config hot-reload** — `INDEX_DB_PATH` is a bootstrap env var (`config._catalogue.BOOTSTRAP_KEYS`), not config-table config — so a rebuilt `Reconciler` always inherits the original writer via `old.store_writer`.

## Gotchas

- **A `reconcile.request` sentinel that arrives DURING the inter-cycle wait does not force a deletion sweep.** `_interruptible_wait` consumes (unlinks) the sentinel and returns `True`, but `_run_loop` discards that return value (the un-assigned `_interruptible_wait(...)` call in `_run_loop`, `src/indexer/daemon/_loop.py` — unlike the assigned `manual_trigger = _consume_sentinel(...)` pattern used for the forced sweep); the next `_run_one_cycle` then calls `_consume_sentinel` on a file that no longer exists, so `manual_trigger` is `False`. The early wake-up and the incremental sync still happen — only the trigger-forces-a-sweep promise in `_wait.py`'s docstring is silently lost. Only a sentinel written while a cycle is actually *running* gets the forced sweep. `rebuild.request` is unaffected (consumed at cycle entry; `search/index_sentinel.py` deliberately writes `reconcile.request` alongside it purely to wake the wait).
- **`SyncReport.skipped` does NOT include light-diff steady-state skips.** A row skipped by `_is_unchanged` never reaches the worker and produces no entry in `outcomes`, so it is invisible to `_tally_outcomes`; only worker-gated `SKIPPED` documents are counted. The steady-state skip count appears solely in the `reconcile.steady_state_skipped` / `reconcile.steady_state_all_unchanged` log events, not in the report or the dashboard summary.
- **`IndexOutcome.SKIPPED` covers two very different things** — a pure no-op skip and a destructive stale-row prune (`delete_documents`). They are distinguishable only by the log event (`worker.document_skipped` vs `worker.stale_document_pruned`); the worker docstring records this as a deliberate choice to keep the `SyncReport` tallies simple.
- **`_boot._start_daemon`'s `finally` block closes the STARTUP paperless client**, but a config hot-reload has already closed it inside `_rebuild_reconciler` and replaced it with a new one. The double close is harmless (httpx close is idempotent) and the new client is left to GC, but the `paperless` name in `_start_daemon` is not the client actually in use after a reload.
- **Two branches, not one, in incremental sync:** watermark `None` → full-document backfill (`_index_page_stream`); watermark set → light `{id, modified}` projection (`_diff_light_page`). Different memory profiles, different Paperless request shapes, different skip semantics. The light path depends on Paperless-ngx honouring the `fields` sparse-fieldset query parameter — if it silently ignored it the code would still be correct, just slower.
- **`chunk_text` raises `ValueError` unless `0 <= overlap < chunk_size`.** The same rule is enforced at config load by `_resolve_chunk_overlap` (`src/common/config/_parsers.py`, called from `_settings.py`), so a bad `CHUNK_OVERLAP`/`CHUNK_SIZE` pair is a config-load error rather than a per-document crash — but the guard is live in the chunker for any direct caller.
- **`_build_meta` stores `modified or ""`** — an empty string is the store's sentinel for an absent Paperless `modified` (the `documents.modified` column is NOT NULL). Unparseable `created`/`modified` values are stored VERBATIM (not dropped) and logged at WARNING (`worker.unparseable_date`).
- **`src/indexer/activity.py` imports `sqlite3`** despite the package docstring's "no direct sqlite3 usage" rule — it needs the `Connection` type and the exception tuple for the best-effort swallow. Every actual write goes through `appdb.reconcile_activity` / `common.heartbeat`. The forbidden-`sqlite3` rule is about the index store, not `app.db`.
- **The daemon is POSIX-only:** `indexer/lock.py` imports `fcntl`.
- **One `ThreadPoolExecutor` per CYCLE, not per batch (IDX-09)** — created in `run_incremental_sync` and threaded through `_fanout`, `_light_diff`, and the retry pass. Do not construct a pool inside `_index_documents`; a backfill of N documents would otherwise spin up `ceil(N/100)` pools and fragment the thread-name numbering.
- **The failed-document retry set is `set(failed_map) - page_ids`, and `page_ids` includes light-diff-SKIPPED ids.** This is safe only because a store row whose `modified` matches the page always corresponds to a successful write (`upsert_document` / `update_metadata` are the only things that write it), so a failed document always has a stale-or-absent stored `modified` and is therefore always re-fetched rather than skipped. Any future code path that writes `modified` without a successful index would break that and strand documents in the failed map.

## Extension points

- **New per-document gate rule** (a new skip condition) → `worker._indexable_content`; it must keep returning `None` for un-indexable content so the no-hash / stale-prune invariant holds.
- **New chunking strategy** → `chunker.chunk_text`; any replacement must still pass through `_cap_chunk_sizes` (or an equivalent ceiling) to keep chunks under the embedding token limit.
- **New persisted reconciler state** → a `StoreWriter.read_meta`/`write_meta` key, following `modified_watermark` / `failed_documents`; the indexer owns every meta key it writes.
- **New cross-process trigger** → drop a sentinel file beside `index.db` and consume it at cycle entry with `_wait._consume_sentinel`, as `rebuild.request` does. Note the wait-window gotcha above before relying on a sentinel to force sweep-like work.
- **New dashboard signal** → an `IndexerActivityRecorder` method; keep the best-effort swallow so `app.db` can never crash the daemon.

## External dependencies

| Dependency | What the indexer uses |
|------------|-----------------------|
| Paperless-ngx REST API (`common.paperless.PaperlessClient`) | `iter_all_documents` (`ordering=modified`, `page_size=100`, optional `modified__gt` server-side filter and `fields` sparse-fieldset projection), `get_document`, `document_exists` (404 → `False`; 401/403/5xx/network errors propagate), `list_correspondents` / `list_document_types` / `list_tags`, `ping`. Transport errors are `PAPERLESS_CALL_EXCEPTIONS = (OSError, httpx.HTTPError, ValueError, KeyError)`. |
| Embedding provider (`common.embeddings.EmbeddingClient`) | OpenAI or Ollama per `EMBEDDING_PROVIDER`; `.embed(texts)` batched at `_BATCH_SIZE = 96`. `EMBEDDING_FAILURE_EXCEPTIONS` is the preflight boundary. The 8191-token input limit is what `_MAX_CHUNK_CHARS` defends. |
| `store.writer.StoreWriter` | The `index.db` write API: `get_index_state`, `get_all_document_ids`, `read_meta`/`write_meta`, `upsert_document`, `update_metadata`, `delete_documents`, `refresh_taxonomy`, `check_embedding_model`, `rebuild_index`, `checkpoint`, `close`. `StoreError` is the fatal-at-boot boundary. Meta keys the indexer owns: `modified_watermark`, `last_reconcile_at`, `last_full_sweep_at`, `failed_documents`. |
| `appdb` (`app.db`) | `appdb.connection.connect` + `appdb.schema.ensure_schema` (best-effort at boot), `appdb.reconcile_activity.record_cycle`, and `common.heartbeat.Heartbeat(name="indexer")` writing `daemon_status`. Purely for the Index dashboard. |
| `common/` | `clock` (`utc_now_iso`, `parse_paperless_timestamp`, `normalise_paperless_timestamp`), `config` (`Settings` + `current_settings` hot-load over `app.db`'s config table), `shutdown` (`register_signal_handlers`, `is_shutdown_requested`), `concurrency` (`llm_limiter`), `logging_config`, `library_setup`. |
| `search/` (file contract only, no import) | `search/index_sentinel.py` (`request_index_rebuild`, called by `index_routes.py` and `settings_routes.py`) drops BOTH `rebuild.request` and `reconcile.request` beside `index.db`; `search/routes.py::_reconcile` drops `reconcile.request` alone. The indexer consumes them (`_wait._consume_sentinel`, `_loop._REBUILD_SENTINEL_NAME`). Each half hard-codes the file names. |
| Third-party | `structlog` (all logging); `fcntl` (the writer flock). |

Config keys read (defaults from `common/config/_settings.py`):

| Key | Default | Notes |
|-----|---------|-------|
| `INDEX_DB_PATH` | `/data/index.db` | Bootstrap env-only (`BOOTSTRAP_KEYS`) — never hot-reloaded. |
| `APP_DB_PATH` | `/data/app.db` | Bootstrap env-only; read via `os.environ` in `_boot.main`. |
| `RECONCILE_INTERVAL` | `300` s | Must be ≥ 1; re-read live each cycle. |
| `DELETION_SWEEP_INTERVAL` | `3600` s | Must be ≥ 1; re-read live each cycle. |
| `DOCUMENT_WORKERS` | `4` | Clamped to a minimum of 1; sizes the per-cycle pool. |
| `CHUNK_SIZE` | `2000` | Must be ≥ 1. In `REINDEX_KEYS`. |
| `CHUNK_OVERLAP` | `256` | Validated `0 <= CHUNK_OVERLAP < CHUNK_SIZE` at config load. In `REINDEX_KEYS`. |
| `ERROR_TAG_ID` | `552` | Optional — `None` disables the error-tag gate. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | In `REINDEX_KEYS` (with `EMBEDDING_PROVIDER`) — a change needs a full rebuild. |
| `EMBEDDING_DIMENSIONS` | `1536` | Must be ≥ 1; stamped into meta by `rebuild_index` / `check_embedding_model`. |
| `LLM_MAX_CONCURRENT` | `4` | Re-sizes `llm_limiter` on hot-reload (0 = unbounded). |

## Related

- Modules: [store](store.md), [search-api](search-api.md) (writes the sentinels), [search-pipeline](search-pipeline.md) (reads the index this daemon writes), [common](common.md)
- Specs: the `SPEC §5.x` markers throughout `src/indexer/` (worker.py, `_boot.py`, `_wait.py`, activity.py, `_loop.py`, the reconciler modules) reference the original semantic-search design spec and the later web-redesign spec — historical design docs never committed to this repo (their legacy `docs/superpowers/specs/` location is gitignored and absent on disk). The only committed spec is `.claude/specs/20260715-flex-and-56-models.md`.
