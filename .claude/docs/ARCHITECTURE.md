<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Architecture

<!-- One concern: structure. Operational material belongs in OPERATIONS.md;
split, never grow, when a second concern appears. -->

## Module map

| Module | Responsibility | Entrypoint | Doc |
|--------|----------------|-----------|-----|
| common | Leaf shared infrastructure: `Settings` (catalogue/parse/load/hot-load), `PaperlessClient`, LLM + embedding clients, retry, concurrency guards, polling loop, circuit breaker, tag/claim/stale-lock helpers, logging, preflight, heartbeat | `src/common/bootstrap.py::bootstrap_process` | [→](modules/common.md) |
| appdb | `app.db`: `users`, `sessions`, `api_keys`, `api_key_usage`, `config`, `recent_searches`, `daemon_status`, `reconcile_activity`, `model_pricing`, `meta` — with its own migration runner | `src/appdb/connection.py::connect` + `src/appdb/schema.py::ensure_schema` | [→](modules/appdb.md) |
| store | `index.db`: schema + migrations, `StoreWriter` (indexer only), `StoreReader` (search only). The only owner of index SQL | `src/store/writer.py::StoreWriter`, `src/store/reader/_reader.py::StoreReader` | [→](modules/store.md) |
| ocr | Vision-LLM transcription daemon: rasterise → per-page OCR with model fallback → assemble → write back | `src/ocr/daemon.py::main` | [→](modules/ocr.md) |
| classifier | Metadata-enrichment daemon: truncate → chat LLM + taxonomy context → filter/enrich tags → PATCH Paperless | `src/classifier/daemon.py::main` | [→](modules/classifier.md) |
| indexer | The only writer of `index.db`: watermark-driven incremental sync, chunk + embed + upsert, deletion sweep | `src/indexer/daemon/_boot.py::main` (re-exported as `indexer.daemon:main`) | [→](modules/indexer.md) |
| search-pipeline | Agentic read side: plan → resolve filters → hybrid retrieve (vector + FTS, RRF) → relevance gate → judge → synthesise → refine | `src/search/core.py::SearchCore` | [→](modules/search-pipeline.md) |
| search-api | HTTP/ASGI surface: `/api/*` routers, `/mcp` (5 tools), SPA catch-all, auth, RBAC, quotas, config hot-reload | `src/search/api.py::main` / `create_app` | [→](modules/search-api.md) |
| web | React 18 + Vite + TS SPA — setup, login, search, library, document, index dashboard, settings, users, API keys | `web/src/main.tsx` (built to `web/dist`) | [→](modules/web.md) |

## Key flows

1. **OCR** — poll `PRE_TAG_ID` → `common.document_iter.iter_documents_by_pipeline_tag` → `common.claims.claim_processing_tag` → `PaperlessClient.download_content` → `ocr.image_converter.open_page_source` (pdf2image/poppler or Pillow → per-page temp files) → `ocr.provider.OcrProvider.transcribe_image` × `PAGE_WORKERS` (model-fallback chain over `OCR_MODELS`) → `ocr.text_assembly.assemble_full_text` → `PaperlessClient.update_document` + tag swap `PRE_TAG_ID` → `POST_TAG_ID` (or `ERROR_TAG_ID`).
2. **Classify** — poll `CLASSIFY_PRE_TAG_ID` (defaults to `POST_TAG_ID`) → claim → `classifier.content_prep` truncation → `classifier.provider` chat call (taxonomy in the stable prompt prefix, document text inside a nonce fence) → `classifier.result.parse_classification_response` → `classifier.quality_gates` → `classifier.tag_filters.enrich_tags` → `TaxonomyCache` id resolution (get-or-create) → `PaperlessClient.update_document_metadata` + tag swap (`CLASSIFY_POST_TAG_ID` is optional — added only when set; `ERROR_TAG_ID` on failure).
3. **Index** — `indexer` cycle: hot-reload config → consume the `reconcile.request` sentinel (and `rebuild.request` → wipe) → `Reconciler.incremental_sync()` (watermark `modified__gt` paging; light `{id, modified}` diff in steady state) → per document `indexer.worker.DocumentIndexer` (content gate → SHA-256 content-hash gate → `chunker.chunk_text` → `EmbeddingClient.embed` → `StoreWriter.upsert_document`) → due-when `Reconciler.deletion_sweep()` → `StoreWriter.checkpoint()` → interruptible wait.
4. **Search** — `POST /api/search` (or `/api/search/stream`, or the `deep_search` MCP tool) → `search.api._resolve_search_core` (per-request `config_version` check) → `SearchCore.answer` → `QueryPlanner` → `retriever.resolve_specs` + hybrid retrieve over `StoreReader` (`vector_search` + `keyword_search`, fused by RRF, `_RRF_K = 60`) → relevance gate → `RelevanceJudge` → `Synthesizer` → optional refinement pass → cited result (+ per-phase trace and USD cost).
5. **Config change** — `PUT /api/settings` (admin) → `settings_service.validate_change_set` (rebuilds `Settings` via `build_settings`) → write `config` table + bump `config_version` in one `BEGIN IMMEDIATE` (scheduling the rebuild sentinel *first* if `reindex_required`, so a re-index key can never persist without its wipe) → every process notices the change at its next safe boundary and rebuilds `Settings`, logging, clients and limiter. No restart.
6. **Rebuild** — `POST /api/index/rebuild` (admin) or a `REINDEX_KEYS` save → `search.index_sentinel.request_index_rebuild` touches `rebuild.request` + `reconcile.request` beside `index.db` → the indexer wipes and re-indexes on its next cycle. The search server never writes `index.db`.

## State & data

| State | Lives in | Written by | Read by |
|-------|----------|-----------|---------|
| Pipeline queue/lock/error state | Paperless-ngx tags | ocr, classifier, search-api (re-queue endpoints) | ocr, classifier |
| Document content + metadata | Paperless-ngx | ocr (content), classifier (metadata), search-api (PATCH/DELETE) | everything |
| Search index (`documents`, `chunks` incl. embedding BLOBs, `chunks_fts`, `taxonomy`, `meta`) | `index.db` | indexer (exclusive `flock`) | search-pipeline / search-api via `StoreReader` |
| Watermark (`modified_watermark`), failed-document map (`failed_documents`), `last_reconcile_at` / `last_full_sweep_at`, embedding fingerprint (`embedding_provider` / `embedding_model` / `embedding_dimensions`) | `index.db` `meta` table | indexer | indexer, search-api (`/api/stats`, `/api/healthz`) |
| Accounts, sessions, API keys, per-key daily token usage, recent searches | `app.db` | search-api | search-api |
| Configuration (`config` table + `config_version`) | `app.db` | search-api (`PUT /api/settings`); any process on first load (`common.config._loader` → `appdb.config.seed_from_env`) | every process (`common.config.current_settings`) |
| Daemon heartbeats + reconcile activity log | `app.db` | all four processes (`common.heartbeat`), indexer (`indexer.activity`) | search-api (Index dashboard) |
| Cached model price book | `app.db` `model_pricing` | search-api `search-price-refresh` thread | search-pipeline (`search.pricing_book`) |

## Boundaries & invariants

- **Import layering (enforced by package docstrings + review, not a tool).** `appdb` and `common` are leaves — `common` may import `appdb` (only `common.heartbeat` does) but never `store`/`search`/`indexer`/`ocr`/`classifier`/FastAPI; `appdb` imports nothing first-party at all. `ocr` and `classifier` may import `common` only (plus `appdb` in their daemon module, for config hot-load + heartbeat). `indexer` may import `store` + `common` (plus `appdb` in `daemon/_boot.py` and `activity.py`). `search` may import `store` + `common` + `appdb`. This is what lets the daemons read `app.db` config without dragging in the sqlite-vec index layer.
- **Single writer, enforced by the OS.** The indexer takes a non-blocking exclusive `fcntl.flock` (`LOCK_EX | LOCK_NB`) on `<INDEX_DB_PATH>.lock` at boot (`indexer.lock.acquire_writer_lock`) and holds it for the process lifetime; a contended lock is `sys.exit(1)`. No other process ever writes `index.db` — the search server asks via sentinel files.
- **Two databases, deliberately.** `index.db` is disposable (a rebuild wipes it); `app.db` is durable (accounts, keys, config, activity). They have separate schema versions and separate — copied, not shared — migration runners (`src/store/migrations.py`, `src/appdb/migrations.py`).
- **Single-path rules.** All Paperless HTTP goes through `common.paperless.PaperlessClient`; all embeddings through `common.embeddings.EmbeddingClient`; all chat completions through `common.llm.OpenAIChatMixin`; all LLM-JSON parsing through `common.llm.extract_json_object`; all `index.db` SQL inside `src/store/`; all `app.db` SQL inside `src/appdb/` (no `.execute(` exists outside those two packages); all frontend network calls inside `web/src/api/`.
- **`Settings` is frozen (`@dataclass(frozen=True, slots=True)`) and rebuilt, never mutated.** Config precedence is `app.db config` table > environment > coded default, and both load paths funnel through `_build_settings`, so validation is identical regardless of source. The daemons detect a change by *identity* (`current_settings()` returns the same cached object when unchanged); the search server compares `config_version` per request in `search.api._resolve_search_core`.
- **`PaperlessClient` is not thread-safe.** Every worker thread builds its own via `common.per_document.run_per_document`, which closes it in a `finally`; the PDF/thumbnail proxies do the same per request. The classifier's shared taxonomy client is the one long-lived exception.
- **Trust boundary: document text is untrusted.** Any OCR/chunk text entering an LLM prompt is wrapped in a fresh per-request nonce fence (`common.prompt_fences.build_data_fence`) inside the *user* message, never the system prompt. Never a static delimiter, never a cached fence.
- **Fail-open where recall matters, fail-closed where safety matters.** Every search LLM stage (planner, judge, synthesiser) degrades to a safe fallback rather than raising; every auth check (`sessions.resolve_session`, `api_keys.resolve_api_key`, `auth.authorise_role`, `setup.verify_setup_token`) returns None/False rather than raising, and an unknown role ranks `-1`, below `readonly` (`_ROLE_RANK` = readonly 0 < member 1 < admin 2).
- **Cost is bounded, not best-effort.** Per-query LLM-call budget (`2 + j + R*(2 + j)`, where `j` is 1 iff the judge gate is on and `R` is `SEARCH_MAX_REFINEMENTS`), `LLM_MAX_CONCURRENT` guard, `SEARCH_MAX_CONCURRENT` single ceiling across HTTP + MCP, per-API-key daily token quota (`SEARCH_KEY_DAILY_TOKEN_QUOTA`; `0` disables), and a write-back circuit breaker that halts a daemon after `DEFAULT_FAILURES_BEFORE_HALT = 3` consecutive Paperless write-back failures.
- **Web layer stack is mechanically enforced.** `web/eslint.config.js` declares ten `eslint-plugin-boundaries` element types (styles, lib, components-primitives, components-layout, components-patterns, api, hooks, features, pages, app) with `default: 'disallow'`; a page may not import a primitive or a pattern. `web/.stylelintrc.json` rejects raw colours, sizes, durations, z-indexes and font families outside `src/styles/{tokens,themes,global}.css`, so every CSS value comes from a token.
