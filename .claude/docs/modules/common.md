<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: common

## Purpose

The leaf shared-infrastructure package (`src/common/`) for every backend process — ocr, classifier, indexer, search. It owns the cross-cutting building blocks no daemon may re-derive: the frozen `Settings` catalogue/parser/loader (config-table-over-environment, hot-loaded without restart), the sole sanctioned Paperless-ngx HTTP client, the LLM chat wrapper, the embedding client, the retry decorator, concurrency guards, the polling loop, the write-back circuit breaker, tag/claim/lock lifecycle helpers, structured logging, preflight checks, the daemon heartbeat, and the shared startup sequence. It imports nothing from any daemon.

## Key files

| File | Role |
|------|------|
| `src/common/bootstrap.py` | Entry point. `bootstrap_process()` runs the 5-step universal startup (`current_settings` → `configure_logging` → `setup_libraries` → `register_signal_handlers` → `llm_limiter.init`) and is the single source of truth for that order. `bootstrap_daemon()` extends it with `PaperlessClient` construction, preflight and the stale-lock sweep, returning `(settings, client)` or `None` on failure. |
| `src/common/config/_catalogue.py` | The key universe: `BOOTSTRAP_KEYS` (`APP_DB_PATH`, `INDEX_DB_PATH` — env-only, never in the DB), `SECRET_KEYS` (`OPENAI_API_KEY`, `PAPERLESS_TOKEN` — masked by the Settings API and by `Settings.__repr__`), `CONFIG_KEYS` (87 keys `PUT /api/settings` accepts, incl. `OPENAI_FLEX_TIER`), `REINDEX_KEYS` (`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `CHUNK_SIZE`, `CHUNK_OVERLAP` — a change warns the operator to re-index). |
| `src/common/config/_settings.py` | The frozen, slotted `Settings` dataclass (flat enumeration of every config field) plus `_build_settings` / `build_settings` — the one validation path both loaders funnel through. Also `_default_models_for` (per-provider model defaults, resolved per step) and the secret-masking `__repr__`. |
| `src/common/config/_parsers.py` | Pure parse/validate/clamp helpers (`_get_int_env`, `_get_csv_env`, `_get_bool_env`, `_get_float_env`, `_resolve_*`). All fail closed with a `ValueError` naming the offending key. Blank/whitespace means "use the coded default" for **int, float and bool** — CSV is the exception (see Gotchas). |
| `src/common/config/_loader.py` | The DB-backed path. `load_settings(app_db_path)` seeds and layers the app.db `config` table over `os.environ`; `current_settings()` / `current_settings_with_version()` are the hot-load accessors backed by `_SETTINGS_CACHE` (app_db_path → `(config_version, Settings)`) and `_SETTINGS_CACHE_LOCK`, rebuilding only when the shared `config_version` counter advances. |
| `src/common/paperless.py` | `PaperlessClient` — the sole sanctioned path for Paperless-ngx HTTP (auth header, retry, pagination via `_list_all`, timeouts). Also exports `PAPERLESS_CALL_EXCEPTIONS` (the tuple every caller catches), `RETRYABLE_HTTP_EXCEPTIONS`, `RETRYABLE_POST_EXCEPTIONS` (connect-phase only) and `is_permanent_paperless_error`. |
| `src/common/paperless_types.py` | TypedDict wire shapes for the Paperless REST API (`PaperlessDocument`, `PaperlessItem`, `PaperlessCustomField`, `DocumentMetadataUpdate`). Re-exported from `common.paperless`; the split exists only to keep `paperless.py` under the size ceiling. |
| `src/common/llm.py` | `OpenAIChatMixin` (retried `_create_completion`, `_create_with_compat` parameter-strip adaptation, `_complete_with_model_fallback`, thread-safe stats), the `_ClientRegistry` two-slot singleton `_openai_holder` (openai/ollama), `set_chat_client`, `LlmCallUsage`, `unique_models`, `extract_json_object`, `ThreadSafeStats`, `_STRIPPABLE_PARAMS`. Also `service_tier_params(flex_enabled, request_timeout)` (explicit `service_tier` + a floored timeout for OpenAI background-daemon calls) and the flex capacity-429 patience loop (`_wait_for_flex_capacity`, `FLEX_MIN_TIMEOUT_SECONDS = 600`, `_FLEX_BACKOFF_CAP_SECONDS = 60.0`) inside `_create_with_compat`. |
| `src/common/library_setup.py` | `setup_libraries(settings)` — builds/replaces the per-provider chat clients (openai slot when `OPENAI_API_KEY` set, ollama slot when `OLLAMA_BASE_URL` set), closes the previous httpx clients on every hot-reload, registers exactly one `atexit` callback, sets Pillow's `MAX_IMAGE_PIXELS = None`. Guarded by `_setup_lock`. |
| `src/common/embeddings.py` | `EmbeddingClient` — the sole embedding path. Builds its **own** `openai.OpenAI` client from `EMBEDDING_PROVIDER` (never the shared chat registry), batches at `_BATCH_SIZE = 96`, retries, raises `EmbeddingError` on non-retryable failure. Exports `EMBEDDING_FAILURE_EXCEPTIONS` so callers never `import openai`. |
| `src/common/retry.py` | The `@retry(retryable_exceptions=...)` decorator: exponential backoff + jitter. Duck-typed — it reads `self.settings.MAX_RETRIES` / `MAX_RETRY_BACKOFF_SECONDS` off the decorated method's owner. |
| `src/common/concurrency.py` | `ConcurrencyGuard` (0 = unbounded, else a `BoundedSemaphore`) and the module-global `llm_limiter` (`LLMConcurrencyLimiter`) whose limit is deferred to bootstrap; `acquire()` before `init()` raises `RuntimeError`. |
| `src/common/daemon_loop.py` | `run_polling_threadpool` — the shared OCR/classifier polling loop. Chunks each batch into sub-batches of `max_workers`, consults `halt_check` between sub-batches **and** inside each worker before the LLM call, isolates per-item failures, exposes `before_each_poll` (config hot-reload hook) and `on_cycle` (heartbeat hook). Returns `CycleOutcome(processed, idle, halted)`. |
| `src/common/circuit_breaker.py` | `WriteBackCircuitBreaker` — counts consecutive Paperless write-back failures (`DEFAULT_FAILURES_BEFORE_HALT = 3`) and trips so the daemon stops pulling work and burning LLM tokens. One success resets the streak; only `reset()` lifts the halt. Exports `HALTED_DETAIL`. |
| `src/common/tags.py` | Tag lifecycle: `extract_tags`, `get_latest_tags`, `remove_stale_queue_tag`, `release_processing_tag`, `finalise_document_with_error` (with a fallback de-queue when the error tag itself is rejected), `pipeline_tag_ids`, `clean_pipeline_tags`. |
| `src/common/claims.py` | `claim_processing_tag` — refresh-before / verify-after best-effort lock on a document via the processing tag. Returns `False` if already claimed or on any error. |
| `src/common/stale_lock.py` | `recover_stale_locks` — the startup sweep that strips orphaned processing-lock tags and re-adds the queue tag. Unconditional (no age or owner check); gated by `STALE_LOCK_RECOVERY`. |
| `src/common/heartbeat.py` | `Heartbeat.beat()` / `beat_idle()` (upserts the daemon's `daemon_status` row, swallowing every `sqlite3.Error` / `OSError`) and `run_heartbeat_ticker` for processes with no natural work cycle (the search server). Imports `appdb.daemon_status` at module scope. |
| `src/common/per_document.py` | `run_per_document` — constructs a fresh `PaperlessClient` per document (the client is not thread-safe), runs the `DocumentProcessor` protocol, always closes the client. Defines `WriteBackOutcome` (`SAVED` / `QUARANTINED` / `None`), which drives the circuit breaker. |
| `src/common/document_iter.py` | `iter_documents_by_pipeline_tag` — the shared queue iterator: fetch by pre-tag, skip non-int ids, skip already-done docs (stripping their stale queue tag), skip docs already claimed via the processing tag. |
| `src/common/model_compat.py` | `model_compat_cache` — the process-wide, lock-guarded singleton mapping model name → set of parameters that model has rejected, so a 400 is paid at most once per model per process. |
| `src/common/preflight.py` | `run_preflight_checks` — fatal Paperless reachability check (raises `PreflightError`), plus non-fatal tag-existence and LLM-reachability warnings. |
| `src/common/shutdown.py` | Process-global `threading.Event` shutdown flag: `request_shutdown` / `is_shutdown_requested` / `reset_shutdown` (test teardown) / `register_signal_handlers` (SIGTERM, SIGINT — main thread only). |
| `src/common/logging_config.py` | `configure_logging(settings)` — structlog + stdlib wiring, JSON or console renderer per `LOG_FORMAT`, clears root handlers first (idempotent), silences httpx/openai loggers to WARNING. |
| `src/common/prompt_fences.py` | `build_data_fence(label=...)` → `DataFence` — per-request 16-byte nonce fences (`_FENCE_NONCE_BYTES = 16`) wrapping untrusted document text in an LLM prompt so it cannot forge the closing marker. Three callers: `src/classifier/provider.py`, and `build_synthesiser_user_message` / `build_judge_user_message` in `src/search/prompts.py`. |
| `src/common/clock.py` | `utc_now_iso`, `parse_paperless_timestamp`, `normalise_paperless_timestamp` — the single normaliser for every timestamp crossing the store boundary (the store compares dates lexicographically). |
| `src/common/constants.py` | `REFUSAL_PHRASES` — the tuple of default `OCR_REFUSAL_MARKERS`, shared by OCR and the classifier's content-quality gate. |
| `src/common/content_checks.py` | `contains_redacted_marker` (bracketed `[… redacted …]` regex) and `is_error_content` (refusal phrase or redaction marker, case-insensitive). |

## Entry points

`common` is a library package with no `__main__`. The four console scripts in `pyproject.toml` (`ocr.daemon:main`, `classifier.daemon:main`, `indexer.daemon:main`, `search.api:main`) all enter through it.

| Door | Callers |
|------|---------|
| `common.bootstrap.bootstrap_daemon()` | `src/ocr/daemon.py:127`, `src/classifier/daemon.py:148` |
| `common.bootstrap.bootstrap_process()` | `src/search/api.py:653` |
| `common.config.current_settings()` | Hot-load config at a safe boundary — every daemon between documents, the search server per request. Also the indexer's inlined boot (`src/indexer/daemon/_boot.py:57`). |
| `common.paperless.PaperlessClient` | All Paperless-ngx HTTP, everywhere. |

## Invariants

| Invariant | Why |
|-----------|-----|
| `common` is the **leaf** package: stdlib + third-party runtime deps + `appdb` only. Never `store`, `ocr`, `classifier`, `indexer`, `search`, or FastAPI. | Verified: the only non-stdlib, non-relative imports across `src/common/` are `httpx`, `openai`, `structlog`, `PIL`, and `appdb`. `appdb` is a sibling leaf, so there is no cycle. |
| Config precedence is exactly: app.db `config` table > environment variable > coded default. | Both construction paths (`load_settings` and `Settings.from_environment`) converge on `_build_settings`, so parsing/validation/clamping is identical regardless of source. |
| `Settings` is `@dataclass(frozen=True, slots=True)` — built once, never mutated mid-run. | A config change produces a **new** object; identity comparison (`latest is not state.settings`) is how the daemons detect a change. |
| `APP_DB_PATH` / `INDEX_DB_PATH` (`BOOTSTRAP_KEYS`) are environment-only, never read from or written to the config table. | They tell a process where its databases live — they cannot live inside one. `_build_settings` has `APP_DB_PATH` force-injected by the loader. |
| Config is hot-loaded, never restart-driven. | `current_settings()` takes a single `BEGIN DEFERRED` snapshot of `(config_version, config_table)` and rebuilds only when `config_version` advanced. Cross-process coordination is that shared integer alone — no signal, no IPC. |
| Boot order is fixed and defined in exactly one place: `current_settings` → `configure_logging` → `setup_libraries` → `register_signal_handlers` → `llm_limiter.init`. | Steps 3 and 5 install module-global singletons (`_openai_holder`, `llm_limiter`) that raise `RuntimeError` if used before init. |
| `PaperlessClient` is **not** thread-safe (single-threaded httpx session). Every worker thread constructs its own. | `run_per_document` enforces the construct → process → close lifecycle. |
| Single-path rules: Paperless HTTP → `PaperlessClient`; embeddings → `EmbeddingClient`; chat completions → `OpenAIChatMixin`; LLM-response JSON parsing → `extract_json_object`. | A bare `openai.embeddings.create` or a bespoke httpx call to Paperless outside these is a guidelines violation. |
| Idempotency-aware retries: GET/PATCH/DELETE retry on `RETRYABLE_HTTP_EXCEPTIONS` (network errors + 5xx); POST retries **only** on connect-phase failures (`RETRYABLE_POST_EXCEPTIONS`). | A `ReadTimeout` mid-response must not re-issue a non-idempotent write — it would duplicate a note. |
| A Paperless 4xx (excluding 408/429) is permanent: `is_permanent_paperless_error` → `True` and the caller quarantines the document. | Re-spending LLM tokens on a write Paperless will never accept is pure waste. 5xx is left to `@retry`. |
| Asymmetric failure signalling, deliberately: `_create_with_compat` returns `None` on terminal failure; `EmbeddingClient` **raises** `EmbeddingError`. | The model-fallback chain needs a non-throwing per-model signal; no such chain exists for embeddings. Do not "fix" either to match the other. |
| A flex-tier `openai.RateLimitError` (`params["service_tier"] == "flex"`) does not count as a terminal per-model failure. | `_create_with_compat` retries the *same* model indefinitely with exponential backoff (capped at `_FLEX_BACKOFF_CAP_SECONDS`) instead of returning `None` — a flex capacity 429 means "no spare capacity right now", not "this model is broken". Two carve-outs stay terminal even on flex: `error.code == "insufficient_quota"` (billing exhausted, waiting never helps) and `is_shutdown_requested()` becoming true mid-wait (returns `None` so the process can still stop promptly). A non-flex `RateLimitError` is unaffected — terminal on the first 429, as before this behaviour existed. |
| `EmbeddingClient.embed` is all-or-nothing — it never returns a short vector list. | A document either embeds wholly (one vector per input, in order) or raises. |
| A heartbeat write must **never** crash a daemon. | `Heartbeat.beat` swallows every `sqlite3.Error` / `OSError` at WARNING (`_HEARTBEAT_WRITE_EXCEPTIONS`). A genuine programming bug (e.g. `TypeError`) is deliberately not caught. |
| The `@retry` contract is structural: the decorated method's owner must expose `self.settings` with `MAX_RETRIES` and `MAX_RETRY_BACKOFF_SECONDS`. | `EmbeddingClient` stores its settings as `self.settings` solely to satisfy this — the attribute must not be renamed. |
| `Settings.__repr__` masks every `SECRET_KEY` with `'********'` (and `str()` delegates to it — no separate `__str__`). | Dropping a `Settings` into a log line cannot leak `OPENAI_API_KEY` or `PAPERLESS_TOKEN`. |
| Untrusted document text in an LLM prompt is wrapped in a fresh per-request `build_data_fence()` nonce — never a static delimiter, never a cached or module-level fence. | Prompt-injection defence: the document cannot forge the closing marker. |

## Gotchas

| Gotcha | Detail |
|--------|--------|
| Blank-value handling still differs **between the scalar and CSV parsers**: int/float/bool fall back to the coded default; required-CSV raises; optional-CSV returns `[]`. | `_get_int_env` / `_get_float_env` / `_get_bool_env` all treat blank as "use the default" (COMMON-20). `_get_csv_env(..., require_non_empty=True)` raises `ValueError: OCR_MODELS must contain at least one model name.` — so does blanking `CLASSIFY_MODELS`. `OCR_REFUSAL_MARKERS` is parsed **without** `require_non_empty`, so blanking it returns `[]` silently — disabling OCR refusal detection with no error. |
| The indexer daemon does **not** go through `bootstrap_process()`. | `src/indexer/daemon/_boot.py` inlines `current_settings()` (:57) → `configure_logging` → `setup_libraries`, calls `register_signal_handlers()` at :113, and `llm_limiter.init()` lives in `src/indexer/daemon/_loop.py:82`. The "single source of truth for boot order" therefore has one caller that re-derives it — a step added to `bootstrap_process` will silently miss the indexer. |
| `load_settings()` has **zero** production callers. | Every process reaches config through `current_settings()`. The only thing exercising `load_settings` is `tests/unit/common/test_config_loader.py`, yet its docstring still presents it as "the production configuration entry point". |
| `common/__init__.py` claims the `appdb` imports are "the deferred ones inside `load_settings` and `current_settings`". | `src/common/heartbeat.py:33` imports `appdb.daemon_status` at module scope. Doc drift, not a cycle (`appdb` is a leaf). |
| `STALE_LOCK_RECOVERY` defaults to `True` and the sweep is unconditional — no age or owner check. | With multiple replicas sharing one processing tag, a restarting replica steals a live peer's lock and re-spends LLM tokens on every rolling restart. **Multi-replica deployments must set it `False`.** |
| `download_stream` / `thumb_stream` bypass `@retry` and hand the caller an iterator that **owns an open httpx response**. | A streaming body cannot be replayed, so retry is off. The iterator must be fully drained or closed or the connection leaks. `count_documents` and `ping` also bypass `@retry` on purpose (single fast shot for the Settings test-connection probe). |
| `OpenAIChatMixin._provider` defaults to `"openai"`. | A new AI step that forgets to override it silently routes to the OpenAI client slot regardless of its own `*_PROVIDER` setting. The five overrides: `src/ocr/provider.py:85`, `src/classifier/provider.py:51`, `src/search/planner.py:92`, `src/search/judge.py:78`, `src/search/synthesizer.py:102`. |
| `_STRIPPABLE_PARAMS` matches by lower-cased **substring** against the 400 message (9 entries, incl. `service_tier`). The `reasoning_effort` and `temperature` matchers are verified against live gpt-5.6 400 responses (2026-07-15); `verbosity` and `max_completion_tokens` remain best-effort and unverified. | A misfiring matcher strips a parameter that was not the problem; damage is bounded only by the registry length (the strip loop caps at `len(_STRIPPABLE_PARAMS) + 1` attempts). Ordering matters: `max_completion_tokens` must precede `max_tokens`. |
| `LLMConcurrencyLimiter.init` with a **changed** limit builds a brand-new guard. | Threads already holding a permit on the old semaphore keep running, so total in-flight LLM calls can briefly exceed the new limit by up to `old_in_flight` (bounded by the longest in-flight call). Documented and accepted, not a bug. |
| `AI_MODELS` is a legacy env-only fallback for `OCR_MODELS` / `CLASSIFY_MODELS`. | Deliberately absent from `CONFIG_KEYS`, so it cannot be set from the Settings UI. Its deprecation warning fires at most once per process (module-global `_ai_models_deprecation_warned`) so the hot-load loop cannot spam the log. |
| `_SETTINGS_CACHE` is process-local module state, privately re-exported from `common.config` purely so tests can reset it between cases. | E.g. `tests/unit/search/test_api_hot_reload.py`. Forgetting to reset it leaks a stale `Settings` into the next test. |
| `EMBEDDING_PROVIDER` is independent of `LLM_PROVIDER` and defaults to `openai`. | Flipping the chat provider does **not** move the embedding space. `EMBEDDING_DIMENSIONS` is deliberately excluded from `REINDEX_KEYS` — it is locked to the model and pinned by the index schema, so a lone change is rejected by validation rather than warned. |
| `OPENAI_API_KEY` is required whenever **any** of the six providers (5 chat steps + embedding) is `openai`. | Only a fully-local deployment may omit it, where it carries `""` rather than `None` (so no call site grows a None-guard). Preflight's `_check_llm_reachable` no-ops when the openai slot is empty, so an all-ollama box gets no LLM reachability check at all. |
| `SEARCH_SERVER_HOST` defaults to `0.0.0.0` (`# nosec B104`-annotated). | Intentional — the server is auth-gated and exposure is expected to be restricted at the reverse proxy — but it is a bind-all default. |
| `WriteBackCircuitBreaker.is_tripped()` stays `True` until `reset()`, even if a late in-flight success clears the streak. | Only a config change (the daemons call `reset()` on hot-reload) or a restart lifts the halt. |
| `finalise_document_with_error` has a second-chance path. | If Paperless rejects the write because `ERROR_TAG_ID` itself is stale/deleted, it retries **without** the error tag so the document at least leaves the queue — otherwise the pre-tag would never be removed and the document would be re-OCR'd forever. |

## Extension points

| Want to… | Do this |
|----------|---------|
| Add a config key | Add the field to `Settings` in `_settings.py`, parse it in `_build_settings` with a `_parsers.py` helper, and add the key to `CONFIG_KEYS` in `_catalogue.py` (omit it there to keep it env-only, as `AI_MODELS` is). Add to `REINDEX_KEYS` only if a change invalidates stored vectors. |
| Add an LLM-backed step | Subclass `OpenAIChatMixin` and **override `_provider`** to return the step's own `*_PROVIDER` setting (default is `"openai"`). Use `_complete_with_model_fallback` for the model chain and `extract_json_object` for the response. |
| Add a polling daemon | Call `bootstrap_daemon(...)`, then `run_polling_threadpool(...)` with `before_each_poll` (hot-reload), `on_cycle` (heartbeat) and `halt_check` (circuit breaker) wired in; process each document through `run_per_document`. |
| Teach the compat layer a new rejected parameter | Add a `(param_key, matcher_substring, stat_key)` row to `_STRIPPABLE_PARAMS` in `llm.py`; keep longer, more specific matchers before their shorter substrings. |
| Add a new Paperless endpoint | Add a method to `PaperlessClient` decorated with `@retry(retryable_exceptions=RETRYABLE_HTTP_EXCEPTIONS)` — or `RETRYABLE_POST_EXCEPTIONS` for a non-idempotent POST. Never call Paperless with a bespoke httpx client. |

## Related

- Modules: [ocr](ocr.md), [classifier](classifier.md), [indexer](indexer.md), [search-pipeline](search-pipeline.md), [search-api](search-api.md), [appdb](appdb.md), [store](store.md)
- Architecture: [ARCHITECTURE](../ARCHITECTURE.md)
