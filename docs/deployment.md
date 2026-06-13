# Deployment

`paperless-ai` is **one Docker image** that can run as up to four small background processes. Each process does one job, and you pick which one by the command you pass the image. A full deployment runs all four side by side, pointed at one Paperless-ngx instance and sharing one `/data` folder.

## In a nutshell

There is a single image — `rossetv/paperless-ai:latest` — and four things it can be:

- **OCR daemon** — reads text off scanned documents (the default command).
- **Classifier daemon** — tags and files those documents once OCR is done.
- **Indexer daemon** — builds a search index from your documents.
- **Search server** — serves the web UI, an HTTP API, and an MCP endpoint on port 8080.

You run as many of these as you want, each as its own container, all sharing the same `/data` volume. **You do not need all four.** OCR and the classifier are useful on their own; the indexer and search server add semantic search on top. The two databases that hold everything live on that shared volume, so the only hard rule is: every container points at the same `/data`.

## The fastest path

The quickest way to a working setup is a single OCR daemon. You need three things from your existing setup — a Paperless URL, a Paperless API token, and an OpenAI key — plus two tag IDs you create in Paperless (one for "needs OCR", one for "done"). Then:

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

Tag a document "needs OCR" in Paperless, and within a few seconds the daemon picks it up. That is the whole loop. Everything below adds the other three processes, the full Compose stack, and the tuning you reach for later.

---

## Prerequisites

Before any of the commands below will work you need:

1. **A running Paperless-ngx instance** with API access enabled.
2. **A Paperless API token** — *Settings → Users & Groups → [your user] → API
   Token* in the Paperless admin.
3. **An AI provider** — an **OpenAI API key**, or a running **Ollama** instance
   (with a vision-capable model pulled, e.g. `gemma3:27b`). An OpenAI key is
   required whenever any step (OCR, classification, planner, judge, answer, or
   embedding) uses OpenAI; a fully-local deployment (all of those on Ollama,
   including `EMBEDDING_PROVIDER=ollama`) needs no key.
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

Run the OCR and classifier daemons one container at a time with `docker run`. The
OCR daemon comes in two flavours depending on your AI provider.

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

Once you want more than one process, Compose is the easier way to manage them.
This stack runs all four. OCR feeds classification through the shared tag `444`;
the indexer reconciles Paperless into the search index; the search server exposes
the web UI, HTTP API, and MCP endpoint on port 8080.

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
      OPENAI_API_KEY: "${OPENAI_API_KEY}"   # required when EMBEDDING_PROVIDER=openai (the default)
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

The daemons take all their direction from Paperless tags: a document tagged
"needs OCR" is work to do, and the daemons swap tags as it moves through the
pipeline. So before anything runs you create those tags in Paperless and tell the
daemons their numeric IDs.

### Required tags

Create these in Paperless (*Admin → Tags*) and note their numeric IDs:

| Purpose | Variable | Example name |
|:---|:---|:---|
| OCR queue | `PRE_TAG_ID` | "OCR Queue" |
| OCR complete | `POST_TAG_ID` | "OCR Complete" |

The numeric ID is in the tag's admin URL — e.g. `/admin/documents/tag/443/change/`
→ `443`.

### Optional tags

These are not required to get going, but each earns its place in a real
deployment:

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

If one OCR or classifier daemon cannot keep up, run several. They all watch the
same Paperless, so the only thing to sort out is stopping two of them grabbing the
same document at once. You do that with a **processing-lock tag**: set
`OCR_PROCESSING_TAG_ID` and/or `CLASSIFY_PROCESSING_TAG_ID` to a dedicated tag ID.
Each instance refreshes the document, checks the lock, patches it on, and
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

You never build the image yourself for normal use — you pull
`rossetv/paperless-ai:latest`. This section is for the curious and for anyone
building it locally.

It is a three-stage build (`Dockerfile`):

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

To do its job, each process sends some document content to an external service.
Know what goes where before you deploy:

| Subsystem | What is sent | Where |
|:---|:---|:---|
| OCR | Page images (base64 PNG) | The vision model provider |
| Classification | OCR text (may be truncated) | The LLM provider |
| Indexing | Document text (chunked) | The embedding provider (`openai` by default; `ollama` if `EMBEDDING_PROVIDER=ollama`) |
| Search | The user's query + retrieved chunks | The LLM provider (planner + synthesiser) |

- **With OpenAI**, this data is sent to OpenAI's API. Review
  [OpenAI's data-usage policies](https://openai.com/policies/api-data-usage-policies).
- **With Ollama for LLM and embeddings** (`LLM_PROVIDER=ollama` and
  `EMBEDDING_PROVIDER=ollama`), OCR, classification, and indexing all stay on
  your own infrastructure — no document content leaves the box.
- **Mixed mode** (e.g. `LLM_PROVIDER=ollama` but `EMBEDDING_PROVIDER=openai`,
  which is the default): OCR and classification run locally, but chunked
  document text is still sent to OpenAI for embedding.

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
