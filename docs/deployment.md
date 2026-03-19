# Deployment

## Prerequisites

Before running the daemons, you need:

1. **A running Paperless-ngx instance** with API access enabled
2. **A Paperless API token** — generate one under *Settings > Users & Groups > [your user] > API Token* in the Paperless admin panel
3. **An AI provider** — either:
   - An **OpenAI API key** (for cloud-hosted models), or
   - A running **Ollama instance** (for self-hosted models)
4. **Tags created in Paperless** — you need at least two tags (e.g. "OCR Queue" and "OCR Complete"). Note down their numeric IDs from the Paperless admin. See [Tag Setup Guide](#tag-setup-guide) below.

---

## Docker Run

### OCR Daemon with OpenAI

```bash
docker run -d --name paperless-ocr \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e PRE_TAG_ID="443" \
  -e POST_TAG_ID="444" \
  rossetv/paperless-ai:latest
```

### OCR Daemon with Ollama

```bash
docker run -d --name paperless-ocr \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e LLM_PROVIDER="ollama" \
  -e OLLAMA_BASE_URL="http://your-ollama:11434/v1/" \
  -e PRE_TAG_ID="443" \
  -e POST_TAG_ID="444" \
  rossetv/paperless-ai:latest
```

Ollama must have a vision-capable model pulled (e.g. `gemma3:27b`). The default model chain for Ollama is `gemma3:27b,gemma3:12b`.

### Classification Daemon

The classification daemon runs from the **same Docker image** with a different command:

```bash
docker run -d --name paperless-classifier \
  -e PAPERLESS_URL="http://your-paperless:8000" \
  -e PAPERLESS_TOKEN="your_paperless_api_token" \
  -e OPENAI_API_KEY="sk-your-openai-key" \
  -e CLASSIFY_PRE_TAG_ID="444" \
  -e CLASSIFY_DEFAULT_COUNTRY_TAG="Ireland" \
  -e ERROR_TAG_ID="552" \
  rossetv/paperless-ai:latest \
  paperless-classifier-daemon
```

`CLASSIFY_PRE_TAG_ID` defaults to `POST_TAG_ID`, so if you run both daemons the classifier automatically picks up documents that finish OCR. You only need to set `CLASSIFY_PRE_TAG_ID` explicitly if you want a different value.

---

## Docker Compose — Full Stack

Run both daemons together. This example chains OCR into classification — documents tagged with `PRE_TAG_ID=443` flow through OCR, then automatically into classification via the shared tag `444`:

```yaml
services:
  paperless-ocr:
    image: rossetv/paperless-ai:latest
    container_name: paperless-ocr
    restart: unless-stopped
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
    environment:
      PAPERLESS_URL: "http://paperless:8000"
      PAPERLESS_TOKEN: "${PAPERLESS_TOKEN}"
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      CLASSIFY_PRE_TAG_ID: "444"       # Picks up where OCR leaves off
      CLASSIFY_DEFAULT_COUNTRY_TAG: "Ireland"
      CLASSIFY_TAG_LIMIT: "5"
      ERROR_TAG_ID: "552"
      DOCUMENT_WORKERS: "4"
      LOG_FORMAT: "json"
```

Store secrets in a `.env` file next to your `docker-compose.yml` and reference them with `${VARIABLE}` syntax.

---

## Tag Setup Guide

### Required Tags

You need to create at least these tags in Paperless (under *Admin > Tags*):

| Tag purpose | Env variable | Example tag name |
|:---|:---|:---|
| OCR queue | `PRE_TAG_ID` | "OCR Queue" |
| OCR complete | `POST_TAG_ID` | "OCR Complete" |

After creating them, note their numeric IDs from the Paperless admin URL or API. For example, if the URL for your "OCR Queue" tag is `/admin/documents/tag/443/change/`, the ID is `443`.

### Optional Tags

| Tag purpose | Env variable | When to use |
|:---|:---|:---|
| Error marker | `ERROR_TAG_ID` | Recommended. Makes it easy to find and investigate failed documents. |
| OCR processing lock | `OCR_PROCESSING_TAG_ID` | Only needed if running multiple OCR daemon instances. See [Multi-Instance Deployments](#multi-instance-deployments). |
| Classification pre-tag | `CLASSIFY_PRE_TAG_ID` | Only set this if you want classification triggered by a different tag than `POST_TAG_ID`. |
| Classification post-tag | `CLASSIFY_POST_TAG_ID` | If set, this tag is added after successful classification. If unset, pipeline tags are simply removed. |
| Classification processing lock | `CLASSIFY_PROCESSING_TAG_ID` | Only needed if running multiple classifier instances. |

### Chaining OCR to Classification

By default, `CLASSIFY_PRE_TAG_ID` equals `POST_TAG_ID`. This means:

1. OCR daemon finishes a document → removes `PRE_TAG_ID`, adds `POST_TAG_ID`
2. Classification daemon sees `POST_TAG_ID` → picks it up automatically
3. After classification → removes `POST_TAG_ID`, applies metadata

**No extra configuration is needed** to chain the two daemons. Just run both with the same `POST_TAG_ID` value.

---

## Multi-Instance Deployments

If you run multiple instances of the same daemon (e.g. for throughput), you need **processing-lock tags** to prevent two instances from processing the same document simultaneously.

Set `OCR_PROCESSING_TAG_ID` (and/or `CLASSIFY_PROCESSING_TAG_ID`) to a dedicated tag ID. Each instance will:

1. **Refresh** the document from Paperless to get the latest tag state
2. **Check** if the processing-lock tag is already present (another instance claimed it) — if so, skip
3. **Patch** the processing-lock tag onto the document
4. **Verify** the tag persisted by re-fetching the document — if another instance overwrote it, skip

This is a best-effort optimistic lock. It eliminates most duplicate processing but is not a strict distributed lock — in rare race conditions, a document may be processed twice (which is safe, as the operations are idempotent).

After processing completes (success or failure), the lock tag is always removed in a `finally` block.

**Source:** `src/common/claims.py`

---

## Privacy & Data Handling

Both daemons send document content to external services for processing:

| Daemon | What is sent | Where it goes |
|:---|:---|:---|
| OCR | Page images (base64-encoded PNG) | Vision model provider (OpenAI API or your Ollama instance) |
| Classification | OCR text (may be truncated) | LLM provider (OpenAI API or your Ollama instance) |

**If you use OpenAI:** Document images and text are sent to OpenAI's API servers. Review [OpenAI's data usage policies](https://openai.com/policies/api-data-usage-policies) to understand how your data is handled.

**If you use Ollama:** All processing stays on your own infrastructure. No data leaves your network.

### Security Recommendations

- Store `PAPERLESS_TOKEN` and `OPENAI_API_KEY` in environment variables or Docker secrets — never hardcode them
- Use `LOG_LEVEL=INFO` or higher in production to avoid logging sensitive document content
- The OpenAI SDK's automatic proxy detection is explicitly disabled (`trust_env=False`) to prevent accidental routing of API calls through unintended proxies in container environments
