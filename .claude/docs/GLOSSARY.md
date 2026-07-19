<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Glossary

## Facts

| Term | Meaning | Source |
|------|---------|--------|
| Paperless-ngx | The upstream document archive. System of record; paperless-ai reads it, writes metadata/content back, and never stores documents itself | `src/common/paperless.py` |
| Pre-tag / post-tag / error tag | The queue / done / quarantine tags that *are* the pipeline's state. Defaults: `PRE_TAG_ID` 443, `POST_TAG_ID` 444, `ERROR_TAG_ID` 552 — all config-overridable. The classifier has its own `CLASSIFY_PRE_TAG_ID` (defaults to `POST_TAG_ID`) and optional `CLASSIFY_POST_TAG_ID` | `src/common/config/_settings.py`, `src/common/tags.py` |
| Processing (claim) tag | The optional per-daemon lock tag (`OCR_PROCESSING_TAG_ID`, `CLASSIFY_PROCESSING_TAG_ID`); a best-effort claim (refresh → add → verify), not an atomic lock | `src/common/claims.py` |
| Quarantine | Error-tagging a document after a *permanent* Paperless write rejection (4xx except 408/429) so it leaves the queue instead of re-burning LLM tokens | `src/common/paperless.py::is_permanent_paperless_error`, `src/common/tags.py::finalise_document_with_error` |
| `WriteBackOutcome` | `SAVED` / `QUARANTINED` / `None` — the only three signals a per-document processor returns; the first two drive the circuit breaker | `src/common/per_document.py` |
| Write-back circuit breaker | Halts a tag daemon after 3 (`DEFAULT_FAILURES_BEFORE_HALT`) consecutive permanent write-back failures; cleared only by a config change or a restart | `src/common/circuit_breaker.py` |
| `REFUSAL_MARK` | The fixed sentinel `CHATGPT REFUSED TO TRANSCRIBE` the transcription prompt tells a vision model to emit when it will not transcribe; also seeded into `OCR_REFUSAL_MARKERS` | `src/common/config/_settings.py::_REFUSAL_MARK`, `src/ocr/prompts.py` |
| Model fallback chain | An ordered model list tried in turn. OCR (`OCR_MODELS`) advances on an API error *or* a refusal; the classifier (`CLASSIFY_MODELS`) on an API error or unparseable JSON; planner/synthesiser (`SEARCH_*_MODEL` + fallbacks) on an API error | `src/ocr/provider.py`, `src/classifier/provider.py`, `src/common/llm.py::_complete_with_model_fallback` |
| Parameter-compat cache | Per-model memory of which chat parameters a model has rejected; a rejected parameter is pre-stripped thereafter, so a 400 is paid at most once per model+parameter per process | `src/common/model_compat.py`, `src/common/llm.py::_create_with_compat` |
| `app.db` | The durable SQLite database: `users`, `sessions`, `api_keys`, `api_key_usage`, `config`, `meta`, `model_pricing`, `daemon_status`, `reconcile_activity`, `recent_searches` | `src/appdb/schema.py` |
| `index.db` | The disposable SQLite search index: `documents`, `chunks` (each row carries an `embedding` BLOB scanned via sqlite-vec), `chunks_fts` (FTS5), `taxonomy`, `meta` | `src/store/schema.py` |
| `config_version` | The monotonic counter in `app.db.meta` bumped by every config write. The entire hot-load mechanism — a process rebuilds `Settings` only when it moves | `src/appdb/config.py` |
| Hot-load | Re-reading configuration at a safe boundary with no restart, no signal and no IPC | `src/common/config/_loader.py` |
| Sentinel | `reconcile.request` / `rebuild.request` — files touched beside `index.db` by the search server and consumed by the indexer. The search server's only command channel to the indexer | `src/search/index_sentinel.py`, `src/indexer/daemon/_loop.py` |
| Watermark | `modified_watermark` in `index.db.meta` — the Paperless `modified` instant the indexer has synced up to, minus `OVERLAP_MARGIN` (10 s) | `src/indexer/reconciler/_incremental.py::OVERLAP_MARGIN` |
| Dead-letter | Dropping a document from the `failed_documents` map after `MAX_CONSECUTIVE_DOCUMENT_FAILURES` (5) consecutive index failures (logged CRITICAL); it is retried only when its content next changes | `src/indexer/reconciler/_failed_documents.py::MAX_CONSECUTIVE_DOCUMENT_FAILURES` |
| Deletion sweep | The periodic reconciliation of index ids against Paperless ids; a partial enumeration prunes nothing | `src/indexer/reconciler/_sweep.py` |
| Chunk | A ~`CHUNK_SIZE`-char window (default 2000) of a document's text with `CHUNK_OVERLAP`; the unit of embedding, vector search and FTS. Hard-capped at 6000 chars (`_MAX_CHUNK_CHARS`) | `src/indexer/chunker.py::_MAX_CHUNK_CHARS` |
| Hash gate | The SHA-256 content check that turns an unchanged document into a `METADATA_ONLY` update instead of a re-embed | `src/indexer/worker.py` |
| `RetrievalPlan` / `RetrievalSpec` | The planner's output: one or more retrieval specs (mode `semantic` or `keyword`, plus filter guesses). On LLM failure it degrades to one broad semantic spec | `src/search/models.py` (defines both), `src/search/planner.py` (produces them) |
| RRF | Reciprocal-rank fusion (`_RRF_K = 60`, 1-based ranks) merging vector and keyword ranks into one score | `src/search/retriever.py::_RRF_K` |
| Judge | The LLM pass returning one keep/drop verdict per candidate document; recall-biased and fail-open (any failure keeps every candidate, `degraded=True`) | `src/search/judge.py` |
| Relevance tier | `strong` / `good` / `partial` / `weak`, derived from vector similarity for the UI. A keyword-only hit (no similarity) is `good` | `src/search/relevance.py` |
| Data fence | The per-request 16-byte (32-hex-char) nonce delimiter wrapping untrusted document text inside an LLM user message (prompt-injection defence) | `src/common/prompt_fences.py` |
| Spend quota | The per-API-key daily (UTC) LLM-token budget, `SEARCH_KEY_DAILY_TOKEN_QUOTA`; a soft cap, and `0` disables it | `src/search/spend_quota.py` |
| Price book | The USD-only model-price table (bundled seed → `app.db` cache → optional operator-configured refresh URL); the trace reads it once per search | `src/search/pricing_book.py`, `src/search/trace.py` |
| Scope (`api` / `mcp` / `admin`) | What an API key may reach. A key is bounded by both its scopes and its owner's current role | `src/search/api_keys.py` |
| Layer stack (frontend) | The ten `eslint-plugin-boundaries` element types — `styles`, `lib`, `components-primitives`, `components-layout`, `components-patterns`, `api`, `hooks`, `features`, `pages`, `app` — with downward-only imports | `web/eslint.config.js` |

## Related

- [OVERVIEW](../OVERVIEW.md) · [ARCHITECTURE](ARCHITECTURE.md) · [PIPELINES](PIPELINES.md)
