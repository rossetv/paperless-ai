# Paperless-ngx AI — OCR, Classification & Semantic Search

AI-powered document transcription, classification, and semantic search for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx), using OpenAI or Ollama vision/language models.

[![Docker Hub](https://img.shields.io/docker/pulls/rossetv/paperless-ai?label=Docker%20Hub)](https://hub.docker.com/r/rossetv/paperless-ai)
[![CI](https://img.shields.io/github/actions/workflow/status/rossetv/paperless-ai/ci.yml?branch=main&label=CI)](https://github.com/rossetv/paperless-ai/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

---

## What This Project Does

This project adds **AI-powered OCR, document classification, and semantic search** to your Paperless-ngx instance. It ships as a single Docker image containing four processes:

**OCR Daemon** — Polls Paperless for documents tagged for OCR, converts pages to images, transcribes them using a vision AI model, and uploads the text back into Paperless.

**Classification Daemon** — Polls Paperless for OCR'd documents, sends the text to an LLM, and enriches the document's metadata: title, correspondent, document type, tags, date, language, and person name.

**Indexer Daemon** — Reconciles Paperless-ngx into a local SQLite search index: chunks and embeds document text, keeps the index in sync with new, changed, and deleted documents.

**Search Server** — Serves a JSON API, a React Web UI, and an MCP endpoint backed by an agentic search pipeline (plan → hybrid retrieve → synthesise).

The OCR and classification daemons use a **tag-driven pipeline** (no external database), support **model fallback chains**, and work with both **OpenAI** and **Ollama**.

---

## How It Works

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

    style A fill:#f0f0f0,stroke:#333
    style H fill:#d4edda,stroke:#28a745
    style I fill:#f8d7da,stroke:#dc3545
```

---

## Quick Start

### Prerequisites

1. A running **Paperless-ngx** instance with API access
2. A **Paperless API token** (Settings > Users & Groups > API Token)
3. An **OpenAI API key** or a running **Ollama instance**
4. At least **two tags** created in Paperless (e.g. "OCR Queue" and "OCR Complete") — note their numeric IDs

### OCR Daemon

```bash
docker run -d --name paperless-ocr \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e PRE_TAG_ID="443" \
  -e POST_TAG_ID="444" \
  rossetv/paperless-ai:latest
```

For Ollama, add these alongside the OpenAI key:
```bash
  -e LLM_PROVIDER="ollama" \
  -e OLLAMA_BASE_URL="http://your-ollama:11434/v1/" \
```

`OPENAI_API_KEY` is still required even with `LLM_PROVIDER=ollama` — it is
loaded by every process so the embedding client can use OpenAI (see the note
under [Semantic Search](#semantic-search--additional-services) below).

### Classification Daemon

Same image, different command:

```bash
docker run -d --name paperless-classifier \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e CLASSIFY_PRE_TAG_ID="444" \
  -e ERROR_TAG_ID="552" \
  rossetv/paperless-ai:latest \
  paperless-classifier-daemon
```

### Docker Compose

```yaml
services:
  paperless-ocr:
    image: rossetv/paperless-ai:latest
    restart: unless-stopped
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      PRE_TAG_ID: "443"
      POST_TAG_ID: "444"
      ERROR_TAG_ID: "552"

  paperless-classifier:
    image: rossetv/paperless-ai:latest
    restart: unless-stopped
    command: ["paperless-classifier-daemon"]
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      CLASSIFY_PRE_TAG_ID: "444"
      ERROR_TAG_ID: "552"
```

---

## Semantic Search — Additional Services

The indexer and search server require a shared volume for the SQLite index file. Add the following services to your Docker Compose stack:

```yaml
services:
  paperless-indexer:
    image: rossetv/paperless-ai:latest
    restart: unless-stopped
    command: ["paperless-indexer-daemon"]
    volumes:
      - paperless-index:/data
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"      # always required — see note below
      INDEX_DB_PATH: "/data/index.db"
      RECONCILE_INTERVAL: "300"
      DELETION_SWEEP_INTERVAL: "3600"

  paperless-search:
    image: rossetv/paperless-ai:latest
    restart: unless-stopped
    command: ["paperless-search-server"]
    volumes:
      - paperless-index:/data
    ports:
      - "8080:8080"
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"      # always required — see note below
      INDEX_DB_PATH: "/data/index.db"
      SEARCH_API_KEY: "${SEARCH_API_KEY}"      # mandatory; server refuses to start without it
    depends_on:
      paperless-indexer:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  paperless-index:
```

> **Note on `OPENAI_API_KEY` with Ollama:** even when `LLM_PROVIDER=ollama`, the embedding client always uses OpenAI (`text-embedding-3-small`) — local Ollama embeddings are not supported. `OPENAI_API_KEY` is therefore **required by every process** (OCR, classifier, indexer, and search server) regardless of the LLM provider setting: configuration loading fails closed at startup if it is missing. With `LLM_PROVIDER=ollama`, the LLM (vision and chat) calls go to Ollama while embeddings go to OpenAI.

---

## Semantic Search — Environment Variables

These variables are read by the indexer daemon and the search server, in addition to the shared variables (`PAPERLESS_URL`, `PAPERLESS_TOKEN`, `OPENAI_API_KEY`, `LLM_PROVIDER`, `OLLAMA_BASE_URL`, `DOCUMENT_WORKERS`, `LOG_LEVEL`, `LOG_FORMAT`).

### Indexer and Store

| Variable | Type | Default | Purpose |
|:---|:---|:---|:---|
| `INDEX_DB_PATH` | string | `/data/index.db` | Path to the SQLite search index file |
| `EMBEDDING_MODEL` | string | `text-embedding-3-small` | OpenAI embedding model (always OpenAI; see note above) |
| `EMBEDDING_DIMENSIONS` | int | `1536` | Vector dimensions — must match the model |
| `EMBEDDING_MAX_CONCURRENT` | int | `4` | Maximum concurrent embedding API calls |
| `RECONCILE_INTERVAL` | int | `300` | Seconds between incremental-sync cycles |
| `DELETION_SWEEP_INTERVAL` | int | `3600` | Seconds between full deletion sweeps |
| `CHUNK_SIZE` | int | `2000` | Characters per text chunk |
| `CHUNK_OVERLAP` | int | `256` | Overlap between adjacent chunks (characters) |

### Search Server

| Variable | Type | Default | Purpose |
|:---|:---|:---|:---|
| `SEARCH_TOP_K` | int | `10` | Documents fed to the synthesiser |
| `SEARCH_MAX_REFINEMENTS` | int | `1` | Maximum agentic refinement steps (hard ceiling: 3 LLM calls per query) |
| `SEARCH_PLANNER_MODEL` | string | `gpt-5.4-mini` / `gemma3:12b` | Query-planning model (cheap, structured extraction) |
| `SEARCH_ANSWER_MODEL` | string | `gpt-5.4` / `gemma3:27b` | Answer-synthesis model (stronger, user-facing prose) |
| `SEARCH_SERVER_HOST` | string | `0.0.0.0` | Bind address for the search server |
| `SEARCH_SERVER_PORT` | int | `8080` | Port for the search server |
| `SEARCH_API_KEY` | string | **required** | API key for all protected endpoints; server refuses to start without it |
| `SEARCH_SESSION_TTL` | int | `604800` | Web UI session-cookie lifetime in seconds (default: 7 days) |
| `SEARCH_MAX_CONCURRENT` | int | `4` | Maximum concurrent `/api/search` requests |

---

## Corruption Recovery Runbook

If `GET /api/healthz` returns `{"status": "index-corrupt"}`:

1. Stop the indexer daemon container.
2. Delete the index file and its companion lock file:
   ```bash
   rm /data/index.db /data/index.db.lock
   ```
3. Restart the indexer daemon. The next reconciliation cycle rebuilds the index from an empty store. At 10,000 documents this takes a few hours and costs approximately $0.60 in embedding API calls.
4. Monitor `GET /api/stats` for an advancing `last_reconcile_at`. The search server returns `503 index-not-ready` until the first reconciliation completes.

The index is a derived artefact — every byte is reconstructable from Paperless-ngx. There is no backup requirement.

The three health states:

| `status` | Meaning |
|:---|:---|
| `ok` | Schema present, at least one reconciliation completed, integrity check passed |
| `index-not-ready` | Database absent, schema not yet applied, or reconciliation has never run |
| `index-corrupt` | Database exists with a schema and reconciliation history, but integrity check failed |

---

## Documentation

| Guide | What it covers |
|:---|:---|
| [Architecture](docs/architecture.md) | Package structure, daemon lifecycle, concurrency model, state management |
| [OCR Pipeline](docs/ocr-pipeline.md) | Image conversion, parallel processing, vision model integration, quality gates |
| [Classification Pipeline](docs/classification-pipeline.md) | Content truncation, taxonomy cache, LLM classification, tag enrichment |
| [Store](docs/store.md) | SQLite search index: schema, writer/reader split, migrations, embedding-model rebuild, corruption recovery |
| [Indexer](docs/indexer.md) | Reconciliation daemon: incremental sync, deletion sweep, failed-document retry, flock single-writer guard |
| [Search](docs/search.md) | Search server: agentic pipeline, RRF fusion, HTTP API, Web UI, MCP endpoint, authentication |
| [Configuration Reference](docs/configuration.md) | All environment variables, pipeline tags, performance tuning |
| [Deployment](docs/deployment.md) | Docker examples, tag setup, multi-instance, privacy |
| [Development](docs/development.md) | Local setup, tests, CI/CD |
| [Resilience](docs/resilience.md) | Retry strategy, fallback chains, error isolation, graceful shutdown |

For AI agents, see [AGENTS.md](AGENTS.md) for a structured codebase guide with file index and common task lookup.
