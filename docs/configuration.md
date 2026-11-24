# Configuration

Every setting below can be changed in the web UI under **Settings**. A change takes effect within one poll cycle on every daemon, with no restart.

Environment variables seed the settings on first start, so a new install can be configured entirely from `docker-compose.yml`. After that, the value saved in the UI wins. Only `APP_DB_PATH` and `INDEX_DB_PATH` stay environment-only, because they say where the settings database lives.

## Paperless

| Variable | Default | |
|:---|:---|:---|
| `PAPERLESS_URL` | `http://paperless:8000` | How the daemons reach the Paperless API. |
| `PAPERLESS_PUBLIC_URL` | `PAPERLESS_URL` | The address your browser uses, for document links in the web UI. |
| `PAPERLESS_TOKEN` | required | Paperless API token. |

## AI provider and models

Each step can use its own provider. A step's provider defaults to `LLM_PROVIDER`; embeddings default to `openai` regardless.

| Variable | Default | |
|:---|:---|:---|
| `LLM_PROVIDER` | `openai` | `openai` or `ollama`. |
| `OCR_PROVIDER`, `CLASSIFY_PROVIDER` | `LLM_PROVIDER` | Override the provider for one daemon. |
| `SEARCH_PLANNER_PROVIDER`, `SEARCH_ANSWER_PROVIDER` | `LLM_PROVIDER` | Override the provider for one search stage. |
| `SEARCH_JUDGE_PROVIDER` | `SEARCH_PLANNER_PROVIDER` | |
| `OPENAI_API_KEY` | | Required while any step, or embeddings, uses OpenAI. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1/` | Must end in `/v1/`. |
| `OPENAI_FLEX_TIER` | `true` | Run OCR and classification on OpenAI's Flex tier: about half price, slower. Search always uses the standard tier. |
| `OCR_MODELS` | `gpt-6-luna,gpt-6.1-terra` | Fallback chain, tried in order. Ollama: `gemma3:27b,gemma3:12b`. |
| `CLASSIFY_MODELS` | `gpt-6-luna,gpt-6.1-terra` | Fallback chain. Ollama: `gemma3:27b,gemma3:12b`. |
| `SEARCH_PLANNER_MODEL` | `gpt-6.1-terra` | Ollama: `gemma3:12b`. |
| `SEARCH_JUDGE_MODEL` | `gpt-6-luna` | Ollama: `gemma3:12b`. |
| `SEARCH_ANSWER_MODEL` | `gpt-6.1-terra` | Ollama: `gemma3:27b`. |
| `OCR_REASONING_EFFORT` | `none` | Each effort is one of `none`, `low`, `medium`, `high`, `xhigh`. Models that don't take the parameter ignore it. |
| `CLASSIFY_REASONING_EFFORT` | `low` | |
| `SEARCH_PLANNER_REASONING_EFFORT` | `medium` | |
| `SEARCH_JUDGE_REASONING_EFFORT` | `none` | |
| `SEARCH_ANSWER_REASONING_EFFORT` | `medium` | |

## Pipeline tags

Tag IDs are the numbers Paperless shows for each tag. The defaults are examples; set them to your own tags.

| Variable | Default | |
|:---|:---|:---|
| `PRE_TAG_ID` | `443` | Documents to OCR. |
| `POST_TAG_ID` | `444` | Added when OCR finishes. |
| `CLASSIFY_PRE_TAG_ID` | `POST_TAG_ID` | Documents to classify, so OCR hands straight over to classification. |
| `CLASSIFY_POST_TAG_ID` | unset | Added when classification finishes. |
| `ERROR_TAG_ID` | `552` | Added when a document fails. |
| `OCR_PROCESSING_TAG_ID`, `CLASSIFY_PROCESSING_TAG_ID` | unset | Lock tags, needed only when several copies of a daemon run at once. |
| `STALE_LOCK_RECOVERY` | `true` | On start, re-queue documents left holding a lock tag by a crash. Set `false` when running several copies, or a restarting copy takes its peers' work. |

## OCR

| Variable | Default | |
|:---|:---|:---|
| `OCR_SKIP_BORN_DIGITAL` | `true` | Skip OCR for PDFs that already contain real text, and pass them on with `POST_TAG_ID`. |
| `OCR_BORN_DIGITAL_MIN_CHARS` | `1` | Text a PDF must hold to count as born-digital. |
| `OCR_BORN_DIGITAL_TAG_ID` | unset | Extra tag for documents that skipped OCR. |
| `OCR_DPI` | `300` | Resolution PDF pages are rendered at. |
| `OCR_MAX_SIDE` | `1600` | Longest side, in pixels, of the image sent to the model. |
| `OCR_IMAGE_DETAIL` | `high` | `high`, `auto` or `low`; lower is cheaper. |
| `OCR_REFUSAL_MARKERS` | built-in list | Phrases that mean the model refused; the next model is tried. |
| `OCR_INCLUDE_PAGE_MODELS` | `false` | Name the model in each page header. |
| `PAGE_WORKERS` | `8` | Pages OCR'd in parallel within one document. |

## Classification

| Variable | Default | |
|:---|:---|:---|
| `CLASSIFY_MAX_PAGES` | `3` | Pages from the start of the document the model sees; `0` for all. |
| `CLASSIFY_TAIL_PAGES` | `2` | Pages from the end it also sees. |
| `CLASSIFY_HEADERLESS_CHAR_LIMIT` | `15000` | Character cap for text without page headers. |
| `CLASSIFY_MAX_CHARS` | `0` | Hard character cap; `0` for none. |
| `CLASSIFY_MAX_TOKENS` | `0` | Output token cap; `0` for the provider's default. |
| `CLASSIFY_TAG_LIMIT` | `5` | Most optional tags kept per document. |
| `CLASSIFY_TAXONOMY_LIMIT` | `40` | Existing names per kind offered to the model for reuse; `0` for all. |
| `CLASSIFY_PERSON_FIELD_ID` | unset | A text custom field to store the person a document is about. |
| `CLASSIFY_DEFAULT_COUNTRY_TAG` | unset | A country tag added to every document, such as `Ireland`. |

## Indexing

Changing the embedding provider or model, or the chunk size or overlap, needs a full re-index from the **Index** page.

| Variable | Default | |
|:---|:---|:---|
| `INDEX_DB_PATH` | `/data/index.db` | Environment only. |
| `APP_DB_PATH` | `/data/app.db` | Environment only. Accounts, API keys and settings. |
| `EMBEDDING_PROVIDER` | `openai` | `openai` or `ollama`. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | |
| `EMBEDDING_DIMENSIONS` | `1536` | Must match the model. |
| `EMBEDDING_MAX_CONCURRENT` | `4` | |
| `CHUNK_SIZE` | `2000` | Characters per chunk. |
| `CHUNK_OVERLAP` | `256` | Must be less than `CHUNK_SIZE`. |
| `RECONCILE_INTERVAL` | `300` | Seconds between syncs with Paperless. |
| `DELETION_SWEEP_INTERVAL` | `3600` | Seconds between checks for documents deleted in Paperless. |

## Search server

| Variable | Default | |
|:---|:---|:---|
| `SEARCH_SERVER_HOST` | `0.0.0.0` | |
| `SEARCH_SERVER_PORT` | `8080` | |
| `SEARCH_FORWARDED_ALLOW_IPS` | `*` | Peers trusted to set `X-Forwarded-*`. Set this to your proxy's address if the port can be reached without going through the proxy. |
| `SEARCH_SESSION_TTL` | `604800` | Seconds a "keep me signed in" session lasts. Other sessions last 8 hours. |
| `SEARCH_MAX_CONCURRENT` | `4` | Searches answered at once. |
| `SEARCH_KEY_DAILY_TOKEN_QUOTA` | `0` | LLM tokens one API key may spend per UTC day; `0` for no limit. Signed-in users are never limited. |
| `SEARCH_CACHE_TTL_SECONDS` | `14400` | How long answers are cached; `0` turns the cache off. It clears whenever the index changes. |
| `SEARCH_TOP_K` | `10` | Documents the answer is written from. |
| `SEARCH_MAX_REFINEMENTS` | `1` | Extra retrieve-and-answer rounds when the first answer falls short. Each round costs several LLM calls. |
| `SEARCH_IDENTITY_AWARE` | `true` | Tell the models who is asking, so "my passport" means yours. |
| `SEARCH_MIN_QUERY_CHARS` | `2` | Shorter queries are rejected before any LLM call. |
| `SEARCH_SKIP_PLANNER_FOR_TRIVIAL` | `false` | Skip the planner for short plain keyword queries. |
| `SEARCH_GATE_ADEQUACY` | `true` | Let the planner ask for a clearer question. |
| `SEARCH_GATE_RELEVANCE` | `true` | Answer "no matches", without writing an answer, when nothing retrieved is close. |
| `SEARCH_RELEVANCE_MIN_SIMILARITY` | `0.60` | Similarity below which, with no keyword hit, nothing counts as close. |
| `SEARCH_GATE_JUDGE` | `true` | A cheap model drops irrelevant documents before the answer is written. |
| `SEARCH_JUDGE_RATIONALES` | `true` | The judge gives a one-line reason per document, shown in the trace. |
| `SEARCH_RELEVANCE_TIER_STRONG` | `0.70` | Similarity for a "Strong match" badge. |
| `SEARCH_RELEVANCE_TIER_GOOD` | `0.66` | Similarity for "Good match". |
| `SEARCH_RELEVANCE_TIER_PARTIAL` | `0.60` | Similarity for "Partial match"; below it, "Weak match". |
| `SEARCH_PLANNER_MAX_SPECS` | `8` | Most sub-queries the planner may split a question into. |
| `SEARCH_PLANNER_TAXONOMY_LIMIT` | `100` | Tag, type and correspondent names shown to the planner; `0` for all. |
| `SEARCH_PER_SPEC_K` | `SEARCH_TOP_K` | Chunks retrieved per sub-query. |
| `SEARCH_MAX_CHUNKS_PER_DOC` | `3` | Most chunks one document may contribute to an answer. |

## Pricing

The cost shown for each search comes from a bundled price table. There is no official price API, so to keep the table current, point the server at a price list you host yourself.

| Variable | Default | |
|:---|:---|:---|
| `PRICING_REFRESH_URL` | unset | An `http(s)` URL serving the JSON below. Unset means no network call. |
| `PRICING_REFRESH_INTERVAL_HOURS` | `24` | |

The list's format, with illustrative prices:

```json
{
  "as_of": "2026-06-10",
  "currency": "USD",
  "models": {
    "gpt-6.1-terra": { "input_per_mtok": 1.0, "output_per_mtok": 5.0 }
  }
}
```

## Daemons

| Variable | Default | |
|:---|:---|:---|
| `POLL_INTERVAL` | `15` | Seconds between checks for tagged documents. |
| `DOCUMENT_WORKERS` | `4` | Documents processed in parallel. |
| `LLM_MAX_CONCURRENT` | `4` | LLM calls in flight per process; `0` for no limit. |
| `MAX_RETRIES` | `3` | Attempts for a failed network call. |
| `MAX_RETRY_BACKOFF_SECONDS` | `30` | Longest wait between attempts. |
| `REQUEST_TIMEOUT` | `180` | Seconds before a model call times out. Search answers on OpenAI use at most 60 per attempt. |
| `LOG_LEVEL` | `INFO` | |
| `LOG_FORMAT` | `console` | `console` or `json`. |
