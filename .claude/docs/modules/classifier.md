<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: classifier

## Purpose

Tag-driven, stateless daemon that enriches Paperless-ngx document metadata with an LLM. It polls Paperless for documents carrying the classify queue tag, truncates their OCR text to a page/char budget, sends it to an OpenAI-compatible chat model with the existing taxonomy as prompt context, and writes back title, correspondent, document type, date, language, tags and the person custom-field — swapping the queue tag for the done tag, requeueing for OCR when there is no content, or applying the error tag on failure.

All pipeline state lives in Paperless tags, so N instances can run concurrently.

**Entrypoint:** `src/classifier/daemon.py::main` — console script `paperless-classifier-daemon` (the `[project.scripts]` entry in `pyproject.toml`) or `python3 -m classifier.daemon` (the `paperless-classifier-daemon` / `classifier.daemon` run-note comment in `Dockerfile`, whose own `CMD` is `["paperless-ai"]`). Library surface re-exported from `src/classifier/__init__.py`: `ClassificationProcessor`, `ClassificationProvider`, `ClassificationResult`, `TaxonomyCache`, `parse_classification_response`.

## Key files

| File | Role |
|------|------|
| `src/classifier/daemon.py` | Process entry point. `bootstrap_daemon()` → shared taxonomy `PaperlessClient` + `TaxonomyCache` → `run_polling_threadpool()` (`common.daemon_loop`). Holds `_DaemonState` (settings, list client, taxonomy client, taxonomy cache, app-db path), whose fields `_reload_if_changed()` (the `before_each_poll` hook) rebuilds when the config changes; owns a process-lifetime `WriteBackCircuitBreaker` and the `Heartbeat(name="classifier")`. `before_each_batch` calls `state.taxonomy_cache.refresh()`. Also runs a `classifier-stall-ticker` daemon thread (`common.heartbeat.run_stall_ticker`, its own `app.db` connection) gated on a `poll_in_flight` event set in `_before_poll` / cleared in `_on_cycle`, beating via the count-preserving `Heartbeat.touch` while a cycle is parked on a slow upstream call; the loop's `finally` stops and joins it (≤5 s). |
| `src/classifier/worker.py` | `ClassificationProcessor` — one instance per document per thread. `process()` = `_prepare_or_divert` (fetch, error-tag check, claim, empty-content requeue, refusal check) → `_truncate_content` → `provider.classify_text` → `_usable_result` → `_apply_classification` → release the processing tag in `finally`. Returns `WriteBackOutcome.SAVED` / `QUARANTINED` / `None`. |
| `src/classifier/provider.py` | `ClassificationProvider(OpenAIChatMixin)` — chat call with model fallback over `unique_models(settings.CLASSIFY_MODELS)`; builds the cache-friendly user message; param compat delegated to `common.llm._create_with_compat`. Returns `(ClassificationResult \| None, model_used)`. |
| `src/classifier/taxonomy.py` | `TaxonomyCache` (RLock-guarded) + `TaxonomyContext`. `refresh()` lists correspondents/types/tags, builds normalised lookup maps and usage-ranked top-N name lists (`_top_names`, capped by `CLASSIFY_TAXONOMY_LIMIT`). `get_or_create_*_id(s)` look up by normalised name and POST-create on miss, with a post-create re-check. `_infer_matching_algorithm()` picks `0` vs `"none"` per Paperless version. |
| `src/classifier/content_prep.py` | Truncation. `truncate_content_by_pages()` slices on `--- Page N ---` headers (head `CLASSIFY_MAX_PAGES` + `CLASSIFY_TAIL_PAGES`, char fallback when headerless); `truncate_content_by_chars()` applies the hard ceiling. Both preserve the trailing `Transcribed by model:` footer. Also builds the truncation notes fed into the prompt. |
| `src/classifier/metadata.py` | `parse_iso_date_prefix`, `parse_document_date` (plausibility window 1900-01-01 … today+366d), `resolve_date_for_tags` (result date → doc `created` → today; injectable clock), `normalise_language` (ISO-639-1 or `"und"`; `None` = leave unchanged), `update_custom_fields` (non-mutating upsert of the person field), `is_empty_classification`. |
| `src/classifier/tag_filters.py` | `dedupe_tags` (order-preserving, case-insensitive), `filter_blacklisted_tags`, `filter_redundant_tags` (drops tags equal to correspondent/type/person), `extract_model_tags` (parses the `Transcribed by model:` footer), `enrich_tags` (required tags always included and not counted against `CLASSIFY_TAG_LIMIT`; optional LLM tags trimmed; whole list lowercased). |
| `src/classifier/quality_gates.py` | `is_generic_document_type()` (rejects `GENERIC_DOCUMENT_TYPES` and `""`) and `needs_error_tag()` (`common.content_checks.is_error_content` over `common.constants.REFUSAL_PHRASES` + `[REDACTED …]` markers). |
| `src/classifier/normalisers.py` | `normalise_simple` (lowercase + whitespace collapse — tags, document types) and `normalise_name` (strips punctuation and trailing `COMPANY_SUFFIXES` — correspondents, so `"Revolut Ltd."` == `"Revolut"`). |
| `src/classifier/prompts.py` | `CLASSIFICATION_PROMPT` (output contract, per-field rules, title templates, fence instructions), `CLASSIFICATION_JSON_SCHEMA` (OpenAI strict structured output), `DEFAULT_CLASSIFY_TEMPERATURE = 0.2`, `DOCUMENT_FENCE_LABEL = "DOCUMENT"`. |
| `src/classifier/constants.py` | `PAGE_HEADER_RE`, `MODEL_FOOTER_RE`, `GENERIC_DOCUMENT_TYPES`, `BLACKLISTED_TAGS` (`{ai, error, indexed, new}`). |
| `src/classifier/result.py` | `ClassificationResult` (frozen, slots, `tags` a tuple) and `parse_classification_response()` — parses LLM JSON via `common.llm.extract_json_object`, coercing a string `tags` to a list, `null` → `""`, non-string scalars → `""`. |
| `src/classifier/__init__.py` | Public surface + the import contract (see Invariants). |

### Tests

| File | Covers |
|------|--------|
| `tests/unit/classifier/conftest.py` | Builders: `make_processor`, `make_doc_with_content`, `make_provider`, `make_completion_response`, `valid_classification_json`, `make_bad_request_error`, `make_api_error`. |
| `tests/unit/classifier/test_worker.py` | `process()` lifecycle: happy path, early exits (claim failure, error tag, empty content, refusal), error paths, lock release, write-back failure (4xx → QUARANTINED, 5xx → re-raise). |
| `tests/unit/classifier/test_worker_metadata.py` | Truncation, tag enrichment, person custom field, stats logging. |
| `tests/unit/classifier/test_daemon.py` | Bootstrap failure, document iteration, `_process_document` client lifecycle, `_process_and_record` ↔ circuit breaker, taxonomy refresh hook, cleanup on `KeyboardInterrupt`, `_reload_if_changed`. |
| `tests/unit/classifier/test_taxonomy.py`, `test_taxonomy_helpers.py` | Cache refresh, name lists (usage ordering, limit, defensive copy), get-or-create incl. refresh-and-retry; helpers `_index_items`, `_match_item`, `_get_usage_count`, `_top_names`. |
| `tests/unit/classifier/test_provider.py`, `test_provider_compat.py` | `classify_text` flow (empty text, model fallback, invalid JSON, stats, prompt construction) and the param-compat retry machinery. |
| `tests/unit/classifier/test_content_prep.py`, `test_metadata.py`, `test_tag_filters.py`, `test_result.py`, `test_normalisers.py`, `test_quality_gates.py`, `test_constants.py` | The pure helpers, one file per module. |
| `tests/integration/test_classifier_pipeline.py` | Real functions end to end: OCR text → truncate → parse → filter → enrich → taxonomy resolution. |
| `tests/e2e/test_classifier_workflow.py` | Full `ClassificationProcessor` against a stateful fake Paperless (`tests.helpers.mocks.make_stateful_paperless`) with a real `TaxonomyCache`. |
| `tests/helpers/factories/_core.py` | `make_settings_obj` / `make_document` / `make_classification_result`. |

Run: `.venv/bin/python -m pytest tests/unit/classifier tests/integration/test_classifier_pipeline.py tests/e2e/test_classifier_workflow.py -q` (400 tests). The repo has a `.venv`; the system `python3` lacks the deps.

## External dependencies

| Dependency | Access path |
|------------|-------------|
| Paperless-ngx REST API | `common.paperless.PaperlessClient` only — `get_documents_by_tag` (listing, via `common.document_iter`), `get_document`, `update_document_metadata`, and `list_*` / `create_*` for correspondents, document types, tags. |
| OpenAI-compatible chat completions (`openai` SDK) | `common.llm.OpenAIChatMixin._create_with_compat`; provider chosen by `settings.CLASSIFY_PROVIDER` ∈ `{openai, ollama}`. |
| `app.db` (SQLite) | `appdb.connection.connect` / `appdb.schema.ensure_schema` — config hot-load (`common.config.current_settings`) and the dashboard heartbeat only. Never the search index DB. |
| `structlog` | Structured logging. |
| `common.*` | bootstrap, config, daemon_loop, per_document, claims, tags, document_iter, circuit_breaker, concurrency (`llm_limiter`), heartbeat, prompt_fences, content_checks, constants, library_setup, logging_config. |

## Invariants

- **Import contract.** `classifier` may import `common` (and `appdb`, for config hot-load + heartbeat only). Never `store`, `indexer`, `search`, `ocr`, `sqlite3`, or FastAPI (`src/classifier/__init__.py` docstring; the `classifier/` row of the import-rule table in `docs/architecture.md`).
- **Stateless.** Every bit of pipeline state is a Paperless tag, so N instances run safely; the optional `CLASSIFY_PROCESSING_TAG_ID` is the claim lock (`common.claims.claim_processing_tag`).
- **One `PaperlessClient` per worker thread** (`common.per_document.run_per_document`) — the client is explicitly not thread-safe (the "not thread-safe" note in `PaperlessClient`'s docstring, `src/common/paperless.py`). The long-lived taxonomy client shared through `TaxonomyCache` is the single documented exception (but see Gotchas).
- **`process()` return contract.** `SAVED` (metadata written), `QUARANTINED` (permanent 4xx → error-tagged so it leaves the queue), or `None` (skipped / requeued / already-errored). Only `SAVED` and `QUARANTINED` reach the `WriteBackCircuitBreaker` (`daemon.py::_process_and_record`); the breaker exists solely to stop a systemic Paperless write failure burning one LLM call per document per poll.
- **Error exits go through `common.tags.finalise_document_with_error`**, never a bare tag strip — `clean_pipeline_tags()` unconditionally removes `ERROR_TAG_ID` too (`worker.py::ClassificationProcessor._prepare_or_divert`).
- **Prompt-cache layout is load-bearing.** `_build_user_message` emits a byte-identical stable prefix (tag-limit guidance + the three taxonomy lists) then the per-document variable suffix (truncation note + document text). Anything per-document added above the fence breaks OpenAI prompt caching.
- **Untrusted OCR text is always nonce-fenced.** `common.prompt_fences.build_data_fence(label=DOCUMENT_FENCE_LABEL)` is generated after the content exists, so the document cannot forge the boundary (`CODE_GUIDELINES` §10.2). The system prompt describes the fence form generically and never carries the nonce.
- **Provider gating.** `reasoning_effort` (default `low`), the `json_schema` `response_format`, and `service_tier` (+ a possibly-floored timeout, via `common.llm.service_tier_params`) are sent only when `CLASSIFY_PROVIDER == "openai"` (`provider.py::_build_params`); `max_tokens` only when `CLASSIFY_MAX_TOKENS > 0`. `temperature` is always requested and stripped by the shared compat layer if rejected.
- **Flex-tier patience.** With `OPENAI_FLEX_TIER` on (default), a Flex capacity `RateLimitError` retries the same model indefinitely (backoff capped at 60s) instead of advancing the fallback chain — see [common](common.md). A shutdown mid-wait yields the same empty/None result as a genuine model failure; `worker.py::ClassificationProcessor._usable_result` checks `common.shutdown.is_shutdown_requested()` and leaves the queue tag instead of error-tagging, so the document is re-attempted next boot instead of quarantined.
- **Required tags are unconditional.** OCR model tags from the footer, the year tag, and `CLASSIFY_DEFAULT_COUNTRY_TAG` are always applied and never count against `CLASSIFY_TAG_LIMIT`; only the LLM's optional tags are trimmed. Every emitted tag is lowercased (`tag_filters.enrich_tags`).
- **`ClassificationResult` is genuinely immutable** — frozen, slots, `tags` a tuple, not a list — so results can cross threads (`result.py::ClassificationResult`).
- **Config hot-load.** Every setting is re-read from `app.db` at the top of each poll (`_reload_if_changed`) except `POLL_INTERVAL` and `DOCUMENT_WORKERS`, fixed for the loop's life. A config change also resets the write-back circuit breaker.

## Gotchas

- **Thread-safety claim vs. code (open question).** A comment in `daemon.py::main`, just above the taxonomy client construction, asserts that "every one of [the taxonomy client's] accesses runs under the cache's RLock", but `TaxonomyCache._get_or_create_item_id` deliberately releases the lock before the HTTP create (`taxonomy.py::_get_or_create_item_id`, "Step 2 — slow path: call the Paperless API without holding the lock"). With `DOCUMENT_WORKERS > 1`, one thread can be POSTing on the shared taxonomy httpx session while another holds the lock doing `refresh()`'s GETs on that same session. The comment overstates the guarantee; treat it as unresolved, not as a proven invariant.
- **Correspondent lookup is substring matching** (`allow_substring=True`, `taxonomy.py::_match_item`): `"Revolut Ltd"` correctly finds `"Revolut"`, but the check is symmetric and unanchored (`normalised in key or key in normalised`), so a short correspondent name can bind to an unrelated longer existing one. Document types and tags use exact normalised matching.
- **An empty `document_type` counts as generic** (`is_generic_document_type("")` is `True`), so a result with no document type is error-tagged, not applied — the LLM must always name a specific type.
- **Rejections by `_usable_result` (empty result, generic type) return `None`** and so never touch the circuit breaker. Only Paperless write-back failures can halt the daemon; a model returning garbage forever will error-tag documents forever without tripping anything.
- **`clean_pipeline_tags()` strips `ERROR_TAG_ID`** along with the queue/processing tags — a naive strip-and-write would silently clear an existing error state. Every error path calls `finalise_document_with_error()`, which re-adds it (and, if Paperless rejects the error tag itself, falls back to de-queueing so the document cannot loop forever).
- **`CLASSIFY_PRE_TAG_ID` defaults to `POST_TAG_ID`** (`src/common/config/_settings.py`, `_build_settings`), so a document that finishes OCR is picked up by the classifier automatically with no extra wiring.
- **`needs_error_tag()` fires on `[REDACTED …]` markers** as well as refusal phrases — a legitimately redacted document body is error-tagged rather than classified.
- **`truncate_content_by_chars()` preserves the footer at the body's expense**: if the footer alone exceeds `CLASSIFY_MAX_CHARS` the body is dropped entirely (`content_prep.py::truncate_content_by_chars`). The char cap is applied after page truncation; both notes are concatenated into the prompt.
- **`parse_document_date()` silently returns `None`** for dates before 1900-01-01 or more than 366 days in the future (logged as `classification.implausible_date`) — an anti-hallucination / anti-injection guard, not a parse bug. `resolve_date_for_tags()` then falls back to the document's `created` field, and finally to today, for the year tag.
- **`parse_classification_response()` maps non-string scalars (bool/int/float) to `""`** — the real defence for Ollama and any provider that cannot enforce the JSON schema; without it a `false` would become the correspondent name `"False"`.
- **`tests/unit/classifier/conftest.py`'s `make_processor` stubs `taxonomy.correspondent_names` / `document_type_names` / `tag_names` on a `MagicMock`** — those methods do not exist on the real `TaxonomyCache` (the real API is `taxonomy_context()` → `TaxonomyContext`). Stale test defaults; don't read them as the interface.
- **Test files are split only for the 500-line ceiling** (`CODE_GUIDELINES` §3.1): `test_worker`/`test_worker_metadata`, `test_provider`/`test_provider_compat`, `test_taxonomy`/`test_taxonomy_helpers`. Check both halves before concluding something is untested.

## Extension points

| Want to… | Change |
|----------|--------|
| Change what the LLM is asked for | `prompts.py` — `CLASSIFICATION_PROMPT` and `CLASSIFICATION_JSON_SCHEMA` must move together; then the field set in `result.py`. |
| Add a taxonomy kind | `taxonomy.py::_TaxonomyKind` + a `_*_kind()` builder (mapping, normaliser, creator, substring policy); `_get_or_create_item_id` is generic over it. |
| Add a pre-LLM rejection rule | `quality_gates.py`, called from `worker._prepare_or_divert` / `_usable_result`. |
| Change tag policy | `tag_filters.py` — `BLACKLISTED_TAGS` (`constants.py`), `enrich_tags` required/optional split. |
| Change the truncation budget | Settings `CLASSIFY_MAX_PAGES`, `CLASSIFY_TAIL_PAGES`, `CLASSIFY_HEADERLESS_CHAR_LIMIT`, `CLASSIFY_MAX_CHARS`; logic in `content_prep.py`. |
| Support another LLM provider | `CLASSIFY_PROVIDER` gating in `provider.py::_build_params` plus the shared `common.llm` compat layer. |

## Related

- Modules: [common](common.md), [ocr](ocr.md) (produces the OCR text and the `Transcribed by model:` footer this module consumes)
