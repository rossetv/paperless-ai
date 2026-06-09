# Deployment

`paperless-ai` ships as **one Docker image** that runs any of its four processes
— the OCR daemon, the classifier daemon, the indexer daemon, and the search
server — chosen by the command you give it. A full deployment runs all four
against one Paperless-ngx instance and one shared `/data` volume.

You do not need all four. The OCR and classifier daemons are useful on their own;
the indexer and search server add semantic search on top.

---

## Prerequisites

1. **A running Paperless-ngx instance** with API access enabled.
2. **A Paperless API token** — *Settings → Users & Groups → [your user] → API
   Token* in the Paperless admin.
3. **An AI provider** — an **OpenAI API key**, or a running **Ollama** instance
   (with a vision-capable model pulled, e.g. `gemma3:27b`). Note: an OpenAI key
   is required even with Ollama, because the embedding step always uses OpenAI.
4. **Tags created in Paperless** — at least an OCR queue tag and an OCR-complete
   tag; note their numeric IDs. See [Tag Setup](#tag-setup) below.

---

## Configuration model

Two things drive a deployment, and it matters which is which:

- **`app.db` config** — almost every setting (tokens, models, tag IDs, tuning
  knobs) lives in the `config` table in `app.db` and is edited from the
  **Settings** screen in the web UI. A change hot-loads across the whole stack
  with **no restart**. On a fresh install the table is seeded from the
  environment, so the environment variables below still work for first boot.
- **Bootstrap environment variables** — only `APP_DB_PATH` and `INDEX_DB_PATH`
  must stay in the environment: they tell each process where its databases live,
  so they cannot themselves live in a database.

See the [Configuration Reference](configuration.md) for the precedence rules and
every variable. The examples below set values via the environment, which is the
natural way to seed a first install.

---

## Docker run — the tag daemons

### OCR daemon (OpenAI)

```bash
docker run -d --name paperless-ocr \
  -v paperless-ai-data:/data \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e PRE_TAG_ID="443" \
  -e POST_TAG_ID="444" \
  -e ERROR_TAG_ID="552" \
  rossetv/paperless-ai:latest
```

`paperless-ai` (the OCR daemon) is the image's default command.

### OCR daemon (Ollama)

```bash
docker run -d --name paperless-ocr \
  -v paperless-ai-data:/data \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e LLM_PROVIDER="ollama" \
  -e OLLAMA_BASE_URL="http://your-ollama:11434/v1/" \
  -e PRE_TAG_ID="443" \
  -e POST_TAG_ID="444" \
  rossetv/paperless-ai:latest
```

Ollama's default model chain is `gemma3:27b,gemma3:12b`. The OpenAI key is still
needed for embeddings if you also run the indexer.

### Classifier daemon

Same image, different command:

```bash
docker run -d --name paperless-classifier \
  -v paperless-ai-data:/data \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e CLASSIFY_PRE_TAG_ID="444" \
  -e CLASSIFY_DEFAULT_COUNTRY_TAG="Ireland" \
  -e ERROR_TAG_ID="552" \
  rossetv/paperless-ai:latest \
  paperless-classifier-daemon
```

`CLASSIFY_PRE_TAG_ID` defaults to `POST_TAG_ID`, so when both daemons run the
classifier automatically picks up documents that finish OCR. You only set it
explicitly to use a different trigger tag.

---

## Docker Compose — the full stack

This runs all four processes. OCR feeds classification through the shared tag
`444`; the indexer reconciles Paperless into the search index; the search server
exposes the web UI, HTTP API, and MCP endpoint on port 8080.

```yaml
services:
  paperless-ocr:
    image: rossetv/paperless-ai:latest
    container_name: paperless-ocr
    restart: unless-stopped
    volumes:
      - paperless-ai-data:/data          # shared by all four services
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      PRE_TAG_ID: "443"
      POST_TAG_ID: "444"
      ERROR_TAG_ID: "552"
      DOCUMENT_WORKERS: "4"
      PAGE_WORKERS: "8"
      LOG_FORMAT: "json"

  paperless-classifier:
    image: rossetv/paperless-ai:latest
    container_name: paperless-classifier
    restart: unless-stopped
    command: ["paperless-classifier-daemon"]
    volumes:
      - paperless-ai-data:/data
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      CLASSIFY_PRE_TAG_ID: "444"         # picks up where OCR leaves off
      CLASSIFY_DEFAULT_COUNTRY_TAG: "Ireland"
      CLASSIFY_TAG_LIMIT: "5"
      ERROR_TAG_ID: "552"
      DOCUMENT_WORKERS: "4"
      LOG_FORMAT: "json"

  paperless-indexer:
    image: rossetv/paperless-ai:latest
    container_name: paperless-indexer
    restart: unless-stopped
    command: ["paperless-indexer-daemon"]
    volumes:
      - paperless-ai-data:/data
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"   # embeddings always use OpenAI
      LOG_FORMAT: "json"

  paperless-search:
    image: rossetv/paperless-ai:latest
    container_name: paperless-search
    restart: unless-stopped
    command: ["paperless-search-server"]
    depends_on:
      - paperless-indexer
    ports:
      - "8080:8080"                       # web UI, HTTP API, MCP
    volumes:
      - paperless-ai-data:/data
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_PUBLIC_URL: "https://paperless.example.com"  # browser-facing deep-links
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      LOG_FORMAT: "json"
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/api/healthz').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 5

volumes:
  paperless-ai-data:
```

> **All four services share the same `/data` volume.** It holds both databases:
> `app.db` (accounts, sessions, API keys, config) and `index.db` (the search
> index). Configuration saved in the web UI hot-loads across the stack with no
> restart.

Store secrets in a `.env` file beside the compose file and reference them with
`${VARIABLE}`.

### Only run the OCR + classifier pair?

Drop the `paperless-indexer` and `paperless-search` services. You still get
AI OCR and classification; you just have no semantic search, and `index.db` is
never created. The `/data` volume is still recommended — it holds `app.db`.

---

## First run of the search server

On first start with no users, the search server enters **setup mode**: it logs a
one-off setup token (`SETUP TOKEN: … — open /setup to create the first admin`).
Open the server (`http://localhost:8080`), go to `/setup`, paste the token, and
create the first admin account. Until that account exists the server exposes only
its setup and health endpoints — there is no default credential and no
`SEARCH_API_KEY`. Programmatic/MCP clients use API keys minted in *Settings → API
Keys*. See [the search doc](search.md) for the full auth model.

The server never crash-loops on an absent or still-building index — it serves
`/api/healthz` and waits. The compose `depends_on` and the healthcheck above
handle startup ordering.

---

## Tag setup

### Required tags

Create these in Paperless (*Admin → Tags*) and note their numeric IDs:

| Purpose | Variable | Example name |
|:---|:---|:---|
| OCR queue | `PRE_TAG_ID` | "OCR Queue" |
| OCR complete | `POST_TAG_ID` | "OCR Complete" |

The numeric ID is in the tag's admin URL — e.g. `/admin/documents/tag/443/change/`
→ `443`.

### Optional tags

| Purpose | Variable | When |
|:---|:---|:---|
| Error marker | `ERROR_TAG_ID` | Recommended — makes failed documents easy to find. |
| OCR processing lock | `OCR_PROCESSING_TAG_ID` | Only when running multiple OCR instances — see below. |
| Classification trigger | `CLASSIFY_PRE_TAG_ID` | Only to trigger classification from a different tag than `POST_TAG_ID`. |
| Classification complete | `CLASSIFY_POST_TAG_ID` | If set, added after successful classification; otherwise pipeline tags are just removed. |
| Classification processing lock | `CLASSIFY_PROCESSING_TAG_ID` | Only when running multiple classifier instances. |

### Chaining OCR into classification

By default `CLASSIFY_PRE_TAG_ID` equals `POST_TAG_ID`, so the chain needs no
extra wiring:

1. OCR finishes a document → removes `PRE_TAG_ID`, adds `POST_TAG_ID`.
2. The classifier sees `POST_TAG_ID` → picks it up.
3. Classification finishes → removes the pipeline tags, writes metadata.

Just run both daemons with the same `POST_TAG_ID`.

---

## Multi-instance deployments

To scale throughput you can run several OCR or classifier instances. To stop two
instances processing the same document, set a **processing-lock tag**
(`OCR_PROCESSING_TAG_ID` and/or `CLASSIFY_PROCESSING_TAG_ID`) to a dedicated tag
ID. Each instance refreshes the document, checks the lock, patches it on, and
re-verifies before processing; the lock is released in a `finally` block.

This is a best-effort optimistic lock, not a strict distributed one — in a rare
race a document may be processed twice, which is safe because the work is
idempotent. See [Resilience](resilience.md#processing-lock-claims-multi-instance).

**The indexer and the search server are single-instance.** Do **not** run two
indexers against the same `/data`: the second takes an exclusive `flock` on the
index, finds it held, logs `CRITICAL`, and exits non-zero. Exactly one indexer is
the index's sole writer.

---

## The Docker image

The image is a three-stage build (`Dockerfile`):

1. **Frontend builder** (`node:22-slim`, on the build host's native arch) — runs
   `npm ci` and `vite build` to produce `web/dist`. The output is
   architecture-neutral, so it is never built under emulation.
2. **Builder / tester / wheel factory** (`python:3.11-slim`, on the target arch)
   — installs the toolchain, builds a wheelhouse of the project and its runtime
   deps, and (unless `RUN_TESTS=0`) runs the full test suite. Building wheels here
   means the final stage never needs a compiler, even on `arm64`.
3. **Production image** (`python:3.11-slim`) — installs only from the offline
   wheelhouse (`--no-index`), adds only `poppler-utils` as a system dependency,
   and runs as a **non-root** user (`appuser`). `MALLOC_ARENA_MAX=2` caps
   steady-state RSS across the long-lived daemons.

CI builds each architecture (`linux/amd64`, `linux/arm64`) on a native runner and
publishes a multi-arch manifest to Docker Hub as `rossetv/paperless-ai:latest`
(and `:sha-<sha>`). See [Development](development.md#cicd-pipeline).

---

## Privacy & data handling

Each subsystem sends content to external services for processing:

| Subsystem | What is sent | Where |
|:---|:---|:---|
| OCR | Page images (base64 PNG) | The vision model provider |
| Classification | OCR text (may be truncated) | The LLM provider |
| Indexing | Document text (chunked) | OpenAI (the embedding model) |
| Search | The user's query + retrieved chunks | The LLM provider (planner + synthesiser) |

- **With OpenAI**, this data is sent to OpenAI's API. Review
  [OpenAI's data-usage policies](https://openai.com/policies/api-data-usage-policies).
- **With Ollama**, OCR and classification stay on your own infrastructure — but
  embeddings still go to OpenAI, so the indexer is not fully offline.

### Security recommendations

- Store `PAPERLESS_TOKEN` and `OPENAI_API_KEY` in a `.env` file or Docker
  secrets — never hardcode them. Once set up, both are managed in the Settings
  screen and stored in `app.db` on the protected `/data` volume.
- Keep `LOG_LEVEL=INFO` or higher in production; secrets and full document
  bodies are never logged regardless.
- The search server binds `0.0.0.0` by design (it is auth-gated). Restrict
  exposure at your reverse proxy or port map, and pin `SEARCH_FORWARDED_ALLOW_IPS`
  to the proxy's CIDR if the uvicorn port is otherwise reachable.
- The OpenAI SDK's proxy auto-detection is disabled (`trust_env=False`) so API
  calls are never accidentally routed through an unintended proxy in a container.
