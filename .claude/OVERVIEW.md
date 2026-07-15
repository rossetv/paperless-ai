<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](INDEX.md)

# paperless-ai — Overview

## What & why

A self-hosted AI companion to a **Paperless-ngx** archive. It transcribes scanned documents with a vision LLM (OCR), enriches their metadata with a chat LLM (classifier), maintains a local SQLite semantic-search index (indexer), and serves an agentic search API + React SPA + MCP endpoint over it (search server). Paperless-ngx stays the system of record; paperless-ai only reads it, writes back metadata/content, and keeps its own derived index.

Everything is **one Docker image running up to four processes**. The two tag daemons are stateless — all pipeline state is a Paperless tag — so they scale horizontally. Configuration lives in a database table, not the environment (bar the two bootstrap DB paths), and hot-loads with no restart.

## Domain concepts

| Term | Meaning |
|------|---------|
| Tag-driven pipeline | A daemon polls Paperless for a *pre-tag*, works the document, then swaps it for the *post-tag* (or the *error tag*). Tags are the whole queue. |
| Pre / post / error tag | `PRE_TAG_ID` (443) → OCR queue; `POST_TAG_ID` (444) → OCR done (and, by default, the classifier's queue); `ERROR_TAG_ID` (552) → quarantined. |
| Processing (claim) tag | Optional per-daemon lock tag. `common.claims.claim_processing_tag` — best-effort refresh/add/verify, not an atomic lock. |
| Quarantine | A permanent (4xx) Paperless rejection → error-tag the document so it leaves the queue instead of re-burning LLM tokens forever. |
| Chunk | A ~`CHUNK_SIZE`-char window of a document's OCR text with `CHUNK_OVERLAP` overlap; the unit of embedding, vector search and FTS. |
| Spec / plan | The planner LLM turns a query into a `RetrievalPlan` of one or more `PlannedSpec`s (semantic and/or keyword, plus free-text filter *guesses*); code resolves each into a `RetrievalSpec` — real taxonomy ids, validated ISO dates. |
| Judge | A cheap LLM pass that keeps/drops each retrieved document (Layer 3 of the relevance stack). |
| `index.db` vs `app.db` | Two separate SQLite databases: the disposable search index vs the durable accounts/config/heartbeat store. Rebuilding one never touches the other. |
| Hot-load | Every process re-reads `config_version` from `app.db` at a safe boundary and rebuilds `Settings` only when it moves. No signal, no IPC, no restart. |
| Sentinel | A file (`reconcile.request`, `rebuild.request`) touched beside `index.db` by the search server; the indexer consumes it. The only cross-process command channel. |

## System boundaries

| External system | Direction | Via |
|-----------------|-----------|-----|
| Paperless-ngx REST API | read + write | `common.paperless.PaperlessClient` (the only sanctioned HTTP path) |
| OpenAI chat / vision | write (prompts) → read | `common.llm.OpenAIChatMixin` |
| OpenAI / Ollama embeddings | write → read | `common.embeddings.EmbeddingClient` (its own client; never the chat registry) |
| Ollama (OpenAI-compatible `/v1/`) | write → read | same two clients, `OLLAMA_BASE_URL` |
| `index.db` (SQLite + sqlite-vec + FTS5) | write: indexer; read: search | `store.writer.StoreWriter` / `store.reader.StoreReader` |
| `app.db` (SQLite) | read + write | `appdb.*` (the only place `app.db` SQL exists) |
| Browser SPA / MCP clients | inbound HTTP | `search.api:create_app` (`/api/*`, `/mcp`, SPA catch-all) |

## Process model

1. **OCR daemon** — `ocr.daemon:main` (`paperless-ai`, the image's default CMD). Polls `PRE_TAG_ID`, rasterises, transcribes pages in parallel, writes content back.
2. **Classifier daemon** — `classifier.daemon:main` (`paperless-classifier-daemon`). Polls `CLASSIFY_PRE_TAG_ID` (defaults to `POST_TAG_ID`), writes title/correspondent/type/date/tags.
3. **Indexer daemon** — `indexer.daemon:main` (`paperless-indexer-daemon`). Single writer of `index.db`, enforced by an `fcntl.flock`; reconcile loop + periodic deletion sweep.
4. **Search server** — `search.api:main` (`paperless-search-server`). One uvicorn process: REST + NDJSON stream + `/mcp` + the built SPA.

All four begin with `common.bootstrap.bootstrap_process()` — the fixed 5-step startup: `current_settings` → `configure_logging` → `setup_libraries` → `register_signal_handlers` → `llm_limiter.init`. The two tag daemons extend it with `bootstrap_daemon()` (Paperless client → preflight → stale-lock sweep).

## Repo layout

```
src/common/      # leaf shared infra: Settings, PaperlessClient, LLM/embeddings, retry, daemon loop, tags
src/appdb/       # app.db: users, sessions, api_keys, config, daemon_status, reconcile_activity, pricing
src/store/       # index.db: schema/migrations, StoreWriter (indexer), StoreReader (search)
src/ocr/         # vision-LLM transcription daemon
src/classifier/  # metadata-enrichment daemon
src/indexer/     # reconciler daemon — the only writer of index.db
src/search/      # search pipeline (core/planner/retriever/judge/synthesizer) + FastAPI/MCP surface
web/             # React 18 + Vite SPA → web/dist, served by the search server
tests/           # unit/ integration/ e2e/ helpers/
docs/            # human-audience prose docs (read-only for Claude)
```

## Key constants

| Constant | Default | Source |
|----------|---------|--------|
| `APP_DB_PATH` | `/data/app.db` (env-only) | `src/common/config/_settings.py` (`_DEFAULT_APP_DB_PATH`) |
| `INDEX_DB_PATH` | `/data/index.db` (env-only) | `src/common/config/_settings.py` (`_DEFAULT_INDEX_DB_PATH`) |
| `PAPERLESS_URL` | `http://paperless:8000` | `src/common/config/_settings.py` (`_DEFAULT_PAPERLESS_URL`) |
| `PRE_TAG_ID` / `POST_TAG_ID` / `ERROR_TAG_ID` | 443 / 444 / 552 | `src/common/config/_settings.py` (`_build_settings`) |
| `POLL_INTERVAL` | 15 s | `src/common/config/_settings.py` (`_build_settings`, `POLL_INTERVAL` field) |
| `RECONCILE_INTERVAL` / `DELETION_SWEEP_INTERVAL` | 300 s / 3600 s | `src/common/config/_settings.py` (`_build_settings`) |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 2000 / 256 chars | `src/common/config/_settings.py` (`_build_settings`), `_parsers.py` (`_resolve_chunk_overlap`) |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | `text-embedding-3-small` / 1536 | `src/common/config/_settings.py` (`_build_settings`) |
| `DOCUMENT_WORKERS` / `PAGE_WORKERS` | 4 / 8 | `src/common/config/_settings.py` (`_build_settings`) |
| `LLM_MAX_CONCURRENT` / `SEARCH_MAX_CONCURRENT` | 4 / 4 (0 = unbounded) | `src/common/config/_settings.py` (`_build_settings`) |
| `SEARCH_SERVER_HOST` / `SEARCH_SERVER_PORT` | `0.0.0.0` / 8080 | `src/common/config/_settings.py` (`_build_settings`), `_parsers.py` (`_resolve_server_port`) |
| `SEARCH_TOP_K` / `SEARCH_MAX_REFINEMENTS` | 10 / 1 | `src/common/config/_settings.py` (`_build_settings`), `_parsers.py` (`_resolve_search_max_refinements`) |
| `REQUEST_TIMEOUT` / `MAX_RETRIES` | 180 s / 3 | `src/common/config/_settings.py` (`_build_settings`) |
| `REFUSAL_MARK` | `CHATGPT REFUSED TO TRANSCRIBE` (fixed, not configurable) | `src/common/config/_settings.py` (`_REFUSAL_MARK`) |
| `OPENAI_FLEX_TIER` | `true` — OpenAI Flex service tier for OCR/classifier | `src/common/config/_settings.py` (`OPENAI_FLEX_TIER` field) |
| `SCHEMA_VERSION` (`index.db`) | 2 | `src/store/schema.py` (`SCHEMA_VERSION`) |
| `SCHEMA_VERSION` (`app.db`) | 8 | `src/appdb/schema.py` (`SCHEMA_VERSION`) |
