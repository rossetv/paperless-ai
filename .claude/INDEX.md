<!-- Claude-maintained; humans never edit. THE registry: every file under
.claude/ has a row in "KB docs" (excepted: INDEX itself, session artefacts
under specs/, plans/, worktrees/, and memory/ bodies — MEMORY.md is their
registry) — an unregistered file is a defect. kb-updater
reconciles this table against disk and code every run. Verified stamps live
ONLY here (date @ short sha of the commit verified against). Injected verbatim
every session, never truncated; registry and module rows are never dropped for
size — compress elsewhere first. Repos outgrowing a single-level index
(roughly >40 modules) split into area sub-indexes, only when actually needed. -->

# paperless-ai — KB Index

## KB docs

| Doc | Purpose | Verified |
|-----|---------|----------|
| [OVERVIEW](OVERVIEW.md) | system summary — always injected | 2026-07-15 @ 538cb86 |
| [DECISIONS](DECISIONS.md) | append-only decision log | 2026-07-14 @ 74d8577 |
| [MEMORY](MEMORY.md) | project memory index — always injected | 2026-07-14 @ 74d8577 |
| [GATES](GATES.md) | gate runbook — the definition of "done" | 2026-07-15 @ 538cb86 |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | module map, flows, state, boundaries | 2026-07-14 @ 74d8577 |
| [OPERATIONS](docs/OPERATIONS.md) | heartbeats, health, halts, runbook | 2026-07-14 @ 74d8577 |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | one image, four processes; CI → Docker Hub | 2026-07-14 @ 74d8577 |
| [CONFIGURATION](docs/CONFIGURATION.md) | config-in-DB, precedence, hot-load, defaults | 2026-07-15 @ 538cb86 |
| [TESTING](docs/TESTING.md) | suites, commands, gates, known skips | 2026-07-15 @ 538cb86 |
| [SECURITY](docs/SECURITY.md) | auth, RBAC, quotas, injection defences, headers | 2026-07-14 @ 74d8577 |
| [API](docs/API.md) | REST + MCP + NDJSON surface and status mapping | 2026-07-14 @ 74d8577 |
| [PIPELINES](docs/PIPELINES.md) | OCR, classification, indexing, search — stage by stage | 2026-07-15 @ 538cb86 |
| [GLOSSARY](docs/GLOSSARY.md) | project vocabulary | 2026-07-14 @ 74d8577 |
| [modules/common](docs/modules/common.md) | shared infrastructure (leaf package) | 2026-07-15 @ 538cb86 |
| [modules/appdb](docs/modules/appdb.md) | `app.db` — accounts, config, heartbeats | 2026-07-14 @ 74d8577 |
| [modules/store](docs/modules/store.md) | `index.db` — schema, writer, reader | 2026-07-14 @ 74d8577 |
| [modules/ocr](docs/modules/ocr.md) | vision-LLM transcription daemon | 2026-07-15 @ 538cb86 |
| [modules/classifier](docs/modules/classifier.md) | metadata-enrichment daemon | 2026-07-15 @ 538cb86 |
| [modules/indexer](docs/modules/indexer.md) | reconciler daemon — sole index writer | 2026-07-14 @ 74d8577 |
| [modules/search-pipeline](docs/modules/search-pipeline.md) | agentic search: plan → retrieve → judge → synthesise | 2026-07-15 @ 538cb86 |
| [modules/search-api](docs/modules/search-api.md) | FastAPI + MCP + SPA surface, auth, RBAC | 2026-07-14 @ 74d8577 |
| [modules/web](docs/modules/web.md) | React/Vite SPA | 2026-07-14 @ 74d8577 |

## Modules

| Module | Purpose | Entrypoint | Doc |
|--------|---------|-----------|-----|
| common | Settings/hot-load, PaperlessClient, LLM + embedding clients, retry, daemon loop, circuit breaker, tags/claims, logging, heartbeat | `src/common/bootstrap.py::bootstrap_process` | [→](docs/modules/common.md) |
| appdb | `app.db`: users, sessions, api_keys, config, key usage, pricing, daemon_status, reconcile_activity | `src/appdb/connection.py::connect` + `src/appdb/schema.py::ensure_schema` | [→](docs/modules/appdb.md) |
| store | `index.db`: schema/migrations, `StoreWriter` (indexer), `StoreReader` (search) | `src/store/writer.py::StoreWriter` · `src/store/reader/_reader.py::StoreReader` | [→](docs/modules/store.md) |
| ocr | Vision-LLM transcription daemon (`paperless-ai`) | `src/ocr/daemon.py::main` | [→](docs/modules/ocr.md) |
| classifier | Metadata-enrichment daemon (`paperless-classifier-daemon`) | `src/classifier/daemon.py::main` | [→](docs/modules/classifier.md) |
| indexer | Reconciler daemon (`paperless-indexer-daemon`); sole writer of `index.db` | `src/indexer/daemon/_boot.py::main` | [→](docs/modules/indexer.md) |
| search-pipeline | Agentic read side: plan → retrieve (vector+FTS, RRF) → gate → judge → synthesise → refine | `src/search/core.py::SearchCore` | [→](docs/modules/search-pipeline.md) |
| search-api | HTTP/ASGI surface (`paperless-search-server`): `/api/*`, `/mcp`, SPA, auth, RBAC, quotas | `src/search/api.py::main` | [→](docs/modules/search-api.md) |
| web | React 18 + Vite + TS SPA, built to `web/dist` | `web/src/main.tsx` | [→](docs/modules/web.md) |

## Goal → start here

| Goal | Start at |
|------|----------|
| Understand the system | [OVERVIEW](OVERVIEW.md) → [ARCHITECTURE](docs/ARCHITECTURE.md) |
| Change how documents are transcribed | [PIPELINES](docs/PIPELINES.md) → `src/ocr/worker.py` → [modules/ocr](docs/modules/ocr.md) |
| Change metadata/tagging behaviour | `src/classifier/worker.py` → [modules/classifier](docs/modules/classifier.md) |
| Change search quality or cost | `src/search/core.py` → [modules/search-pipeline](docs/modules/search-pipeline.md) |
| Add or change an HTTP/MCP endpoint | [API](docs/API.md) → `src/search/routes.py` → [modules/search-api](docs/modules/search-api.md) |
| Add a config key | [CONFIGURATION](docs/CONFIGURATION.md) → `src/common/config/_catalogue.py` |
| Touch the index schema or SQL | `src/store/schema.py` + `src/store/migrations.py` → [modules/store](docs/modules/store.md) |
| Touch accounts, sessions, keys or `app.db` schema | `src/appdb/` → [modules/appdb](docs/modules/appdb.md) |
| Build UI | `DESIGN.md` (law) → `web/src/styles/tokens.css` → [modules/web](docs/modules/web.md) |
| Diagnose a stuck/halted daemon | [OPERATIONS](docs/OPERATIONS.md) |
| Ship / debug the image or CI | [DEPLOYMENT](docs/DEPLOYMENT.md) |
| Run the tests | [TESTING](docs/TESTING.md) |

## Human docs (read-only for Claude)

| Doc | Covers |
|-----|--------|
| `CODE_GUIDELINES.md` | the law — reviewer enforces every section (§3.1 file ceiling, §9.1 SQL ownership, §10 security, §12 frontend) |
| `DESIGN.md` | visual language — reviewer enforces on UI diffs |
| `AGENTS.md` | agent-facing contribution rules |
| `README.md` | product intro and setup |
| `docs/` | human-audience prose: `architecture`, `configuration`, `deployment`, `development`, `resilience`, `cache`, `store`, `indexer`, `search`, `search-pipeline`, `ocr-pipeline`, `classification-pipeline` |

## Central vs peripheral

- **Central** (changes fan out): `src/common/config/_settings.py` + `_catalogue.py` (every process's `Settings`), `src/common/paperless.py` (all Paperless HTTP), `src/common/llm.py` (all chat calls), `src/store/schema.py` + `src/store/migrations.py` (index shape), `src/appdb/schema.py` (app.db shape), `src/search/api.py` (app wiring + hot-reload cache), `web/src/styles/tokens.css` (every visual value).
- **Peripheral** (isolated): `src/ocr/image_converter.py`, `src/ocr/text_assembly.py`, `src/classifier/tag_filters.py` / `normalisers.py` / `metadata.py`, `src/search/dates.py` / `relevance.py` / `text.py` / `pricing.py`, `src/indexer/chunker.py`, and individual `web/src/components/primitives/*`.
