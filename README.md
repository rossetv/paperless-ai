<div align="center">

# Paperless-ngx AI

**Reads your scans, files them for you, and answers questions about them.**

[![Docker Hub](https://img.shields.io/docker/pulls/rossetv/paperless-ai?label=Docker%20Hub)](https://hub.docker.com/r/rossetv/paperless-ai)
[![CI](https://img.shields.io/github/actions/workflow/status/rossetv/paperless-ai/ci.yml?branch=main&label=CI)](https://github.com/rossetv/paperless-ai/actions)

<img src="docs/how-it-works.svg" width="830" alt="A blurry scan with no title or tags is read and filed as 'March electricity bill' from City Power, then the question 'How much was my last electricity bill?' is answered with a link to that document.">

</div>

An add-on for [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx). It runs as containers beside your Paperless and writes everything it learns back into it. It works with OpenAI, or entirely on your own machine with Ollama.

## What's inside

One Docker image that runs as four services. Start the ones you want.

| Service | Command | It… |
|:---|:---|:---|
| **OCR** | *(default)* | reads the text off every page of a scan |
| **Classifier** | `paperless-classifier-daemon` | gives it a title, sender, type, tags and date |
| **Indexer** | `paperless-indexer-daemon` | makes your documents searchable by meaning |
| **Search** | `paperless-search-server` | answers questions, in the web UI, over an API, or to an AI assistant |

OCR and the classifier on their own already file your documents in Paperless. Add the indexer and search to ask questions.

## Get started

You need Paperless-ngx, its API token (*Settings → Users & Groups → API Token*) and an OpenAI API key.

**1. Create three tags in Paperless**: *needs OCR*, *OCR done* and *failed*. Their numeric IDs are listed at `http://your-paperless:8000/api/tags/`.

**2. Save this as `docker-compose.yml`**, with your Paperless address and tag IDs:

```yaml
x-paperless-ai: &paperless-ai
  image: rossetv/paperless-ai:latest
  restart: unless-stopped
  volumes:
    - paperless-ai-data:/data
  environment:
    PAPERLESS_URL: http://paperless:8000
    PAPERLESS_TOKEN: ${PAPERLESS_TOKEN}
    OPENAI_API_KEY: ${OPENAI_API_KEY}
    PRE_TAG_ID: "443"      # needs OCR
    POST_TAG_ID: "444"     # OCR done
    ERROR_TAG_ID: "552"    # failed

services:
  ocr:
    <<: *paperless-ai
  classifier:
    <<: *paperless-ai
    command: paperless-classifier-daemon
  indexer:
    <<: *paperless-ai
    command: paperless-indexer-daemon
  search:
    <<: *paperless-ai
    command: paperless-search-server
    ports:
      - "8080:8080"

volumes:
  paperless-ai-data:
```

**3. Start it**, with your secrets beside it in `.env`:

```bash
printf 'PAPERLESS_TOKEN=...\nOPENAI_API_KEY=sk-...\n' > .env
docker compose up -d
```

**4. Create your account.** Copy the one-time setup token from the logs, open `http://localhost:8080/setup` and paste it:

```bash
docker compose logs search | grep "SETUP TOKEN"
```

**5. Try it.** Tag a document *needs OCR*. Within a minute it has text, then a title and tags, then you can ask about it.

## Settings

Everything is set in the web UI under **Settings**, and takes effect within seconds, without a restart. The values in `docker-compose.yml` only fill in the first start. Every setting is listed in [docs/configuration.md](docs/configuration.md).

## Run it locally with Ollama

Point everything at Ollama, embeddings included, and no OpenAI key is needed:

```yaml
    LLM_PROVIDER: ollama
    EMBEDDING_PROVIDER: ollama
    OLLAMA_BASE_URL: http://ollama:11434/v1/
    EMBEDDING_MODEL: nomic-embed-text
    EMBEDDING_DIMENSIONS: "768"
```

Pull `gemma3:27b` and `gemma3:12b` into Ollama first; they are the default models.

## Connect an AI assistant

The search server is an [MCP](https://modelcontextprotocol.io) server at `http://your-host:8080/mcp`. Create a key under **Settings → API Keys** with the `mcp` scope and send it as `Authorization: Bearer sk-pls-…`. Your assistant can then search, read and filter your documents for free, or call `deep_search` to have the server write the answer.

## If something goes wrong

`GET /api/healthz` returns `ok` when search is ready, `index-not-ready` while the first index is still being built, and `index-corrupt` if the index file is damaged.

The index can always be rebuilt from Paperless. Stop the indexer, delete `index.db` and `index.db.lock` from the `/data` volume, and start it again. Your accounts and settings, kept in `app.db`, are not touched.

## Development

```bash
pip install -e . -r requirements-dev.txt
pytest -n auto
ruff check src tests && mypy src

cd web && npm ci
npm run dev        # the web UI, with hot reload
npm test
```
