# AGENTS.md — Paperless-AI Codebase Guide

AI-powered OCR and document classification daemons for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx). Python 3.11, OpenAI/Ollama LLMs, tag-driven pipeline, no database.

---

## Documentation Index

| Document | What it covers |
|:---|:---|
| [Architecture](docs/architecture.md) | Package structure, daemon lifecycle, concurrency model, thread safety, state management, full project tree |
| [OCR Pipeline](docs/ocr-pipeline.md) | OCR daemon flow, image conversion, parallel page processing, vision model integration, blank page detection, text assembly, quality gates |
| [Classification Pipeline](docs/classification-pipeline.md) | Classification daemon flow, content truncation, taxonomy cache, LLM classification, parameter compatibility, metadata application, tag enrichment |
| [Configuration](docs/configuration.md) | All environment variables by category, pipeline tag state diagram, performance tuning recommendations |
| [Deployment](docs/deployment.md) | Docker run/compose examples, tag setup guide, multi-instance deployments, privacy & data handling |
| [Development](docs/development.md) | Local setup, running tests, test organization, adding tests, CI/CD pipeline, Docker image build |
| [Resilience](docs/resilience.md) | Retry strategy, model fallback chains, error isolation, processing locks, stale lock recovery, graceful shutdown |

---

## Architecture Overview

```mermaid
flowchart LR
    A["Document ingested\ninto Paperless"] --> B["User or workflow\nadds PRE_TAG_ID"]
    B --> C["OCR Daemon\npicks it up"]
    C --> D{"OCR\nsucceeds?"}
    D -- Yes --> E["Remove PRE_TAG_ID\nAdd POST_TAG_ID"]
    E --> F["Classification Daemon\npicks it up"]
    F --> G{"Classification\nsucceeds?"}
    G -- Yes --> H["Enriched document\nTitle, tags, metadata set\nPipeline tags removed"]
    D -- No --> I["Add ERROR_TAG_ID\nRemove pipeline tags"]
    G -- No --> I
```

Two independent daemons connected by a **tag-driven pipeline**:

1. **OCR Daemon** (`src/ocr/`) — Downloads documents, converts pages to images, transcribes via vision LLM, writes text back to Paperless
2. **Classification Daemon** (`src/classifier/`) — Reads OCR text, classifies via LLM, applies metadata (title, correspondent, tags, date, type, language, person)
3. **Common** (`src/common/`) — Shared infrastructure: config, Paperless API client, daemon loop, LLM wrapper, retry logic, tag management

Both use Paperless-ngx tags as the sole state mechanism — no database, no message queue. Daemons are stateless and restartable.

---

## Key File Index

### Entry Points

| File | Purpose |
|:---|:---|
| `src/ocr/daemon.py` | OCR daemon entry point (CLI: `paperless-ai`) |
| `src/classifier/daemon.py` | Classification daemon entry point (CLI: `paperless-classifier-daemon`) |

### OCR Pipeline (`src/ocr/`)

| File | Purpose |
|:---|:---|
| `worker.py` | Per-document OCR orchestrator — download, convert, OCR pages, assemble, upload |
| `provider.py` | Vision model API calls with model fallback chain and refusal detection |
| `prompts.py` | System prompt for the transcription vision model |
| `image_converter.py` | PDF rasterization (via Poppler), multi-frame TIFF handling |
| `text_assembly.py` | Combines per-page results with page headers and model footer |

### Classification Pipeline (`src/classifier/`)

| File | Purpose |
|:---|:---|
| `worker.py` | Per-document classification orchestrator — validate, truncate, classify, apply metadata |
| `provider.py` | LLM classification calls with model fallback and parameter compatibility |
| `prompts.py` | Classification system prompt and JSON schema definition |
| `taxonomy.py` | Thread-safe cache of Paperless correspondents, document types, and tags |
| `content_prep.py` | Page-based and character-based content truncation |
| `metadata.py` | Date parsing, language coercion, custom field handling |
| `tag_filters.py` | Tag blacklisting, deduplication, enrichment (year, country, model tags) |
| `quality_gates.py` | Rejects empty results and generic document types |
| `result.py` | `ClassificationResult` dataclass and JSON parser |
| `normalizers.py` | String normalization (company suffix stripping) |
| `constants.py` | Regex patterns, tag blacklists, generic document type list |

### Shared Infrastructure (`src/common/`)

| File | Purpose |
|:---|:---|
| `config.py` | `Settings` class — loads and validates all environment variables |
| `paperless.py` | `PaperlessClient` — Paperless-ngx REST API client with retry |
| `daemon_loop.py` | `run_polling_threadpool()` — reusable polling loop with ThreadPoolExecutor |
| `llm.py` | `OpenAIChatMixin` — OpenAI SDK wrapper with retry and stats |
| `retry.py` | `@retry` decorator — exponential backoff with jitter |
| `bootstrap.py` | Startup sequence: settings → logging → LLM → signals → preflight |
| `tags.py` | Tag extraction, cleanup, refresh, finalization |
| `claims.py` | Processing-lock tag claim and release |
| `stale_lock.py` | Stale lock recovery on startup |
| `shutdown.py` | SIGTERM/SIGINT signal handling with thread-safe flag |
| `concurrency.py` | LLM concurrency semaphore |
| `preflight.py` | Startup validation (Paperless connectivity, tag existence) |
| `document_iter.py` | Document queue filtering (skip processed, claimed, errored) |
| `content_checks.py` | OCR error/refusal marker detection |
| `logging_config.py` | structlog configuration (JSON or console output) |
| `library_setup.py` | OpenAI/httpx client singleton initialization |
| `constants.py` | Shared constants (refusal phrases, error markers) |

### Tests (`tests/`)

| Path | Purpose |
|:---|:---|
| `helpers/factories.py` | Test data factories: `make_settings_obj()`, `make_document()`, `make_classification_result()` |
| `helpers/mocks.py` | Mock builders: `make_mock_paperless()`, `make_mock_ocr_provider()` |
| `unit/` | Unit tests mirroring `src/` layout |
| `integration/` | Cross-module pipeline integration tests |
| `e2e/` | Full daemon workflow end-to-end tests |

---

## Common Agent Tasks

### "Where is X configured?"
All environment variables → `src/common/config.py` (`Settings` class). Full reference → [docs/configuration.md](docs/configuration.md)

### "How does the pipeline work?"
Tag-driven state machine. Overview → [Architecture](docs/architecture.md#state-management). OCR details → [docs/ocr-pipeline.md](docs/ocr-pipeline.md). Classification details → [docs/classification-pipeline.md](docs/classification-pipeline.md).

### "How does the LLM integration work?"
OpenAI SDK wrapper in `src/common/llm.py`. OCR uses vision models via `src/ocr/provider.py`. Classification uses chat models via `src/classifier/provider.py`. Both support model fallback chains.

### "What prompts are used?"
OCR transcription prompt → `src/ocr/prompts.py`. Classification prompt + JSON schema → `src/classifier/prompts.py`.

### "How are documents processed concurrently?"
Two-level ThreadPoolExecutor. `DOCUMENT_WORKERS` threads at daemon level, `PAGE_WORKERS` threads within each OCR document. LLM calls bounded by semaphore. Details → [Architecture — Concurrency Model](docs/architecture.md#concurrency-model).

### "How are errors handled?"
Retry with exponential backoff → `src/common/retry.py`. Model fallback → `src/ocr/provider.py`, `src/classifier/provider.py`. Per-document isolation → `src/common/daemon_loop.py`. Full details → [docs/resilience.md](docs/resilience.md).

### "How do I add a new test?"
Mirror source layout. Use factories from `tests/helpers/factories.py`. Details → [docs/development.md](docs/development.md#adding-new-tests).

### "How does the Docker image work?"
Multi-stage build. Tests run in builder stage. Production stage is minimal with non-root user. Details → [docs/development.md](docs/development.md#docker-image).

### "How do tags flow through the pipeline?"
State diagram → [docs/configuration.md](docs/configuration.md#tag-state-flow). Tag setup → [docs/deployment.md](docs/deployment.md#tag-setup-guide).
