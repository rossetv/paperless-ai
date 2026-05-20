# The Search Server

`src/search/` is the read side of the semantic-search subsystem. It exposes an agentic search pipeline over three surfaces — an HTTP JSON API, a React Web UI, and an MCP endpoint — all from a single process.

**Entry point:** `search.api:main` (CLI command: `paperless-search-server`)

The search server is **read-only**. It accesses the store exclusively through `StoreReader`, which has no write methods. The indexer daemon holds the sole write lock.

---

## Process Layout

One uvicorn process serves everything:

| Path | Purpose |
|:---|:---|
| `GET /` and static assets | The built React SPA (from `web/dist`) |
| `POST /api/auth/login` | API-key exchange for a signed session cookie |
| `GET /api/healthz` | Liveness; unauthenticated |
| `POST /api/search` | Full agentic search pipeline |
| `GET /api/facets` | Taxonomy facets for the filter panel |
| `GET /api/stats` | Index statistics |
| `POST /api/reconcile` | Manual reconciliation trigger |
| `/mcp` | MCP streamable-HTTP ASGI app |

The MCP ASGI app is mounted into the same uvicorn instance at `/mcp` before any catch-all routes — no second process, no additional port.

---

## The Agentic Search Pipeline (`search/core.py`)

The pipeline is a pure library. `SearchCore` wires the planner, retriever, and synthesiser together. Two public entry points:

- `answer(query, ui_filters)` — full pipeline with synthesis. Used by `POST /api/search` and the MCP `ask_documents` tool.
- `retrieve(query, ui_filters)` — plan and retrieve only; no synthesis. Used by the MCP `search_documents` tool (the calling agent synthesises, saving one LLM call).

Every stage takes its LLM client and store reader by injection, so the pipeline is testable offline.

### Hard LLM-call ceiling

The guaranteed ceiling is **three LLM chat calls per query**: one planner call + at most two synthesiser calls. The query embedding is not a chat call and is not counted.

The ceiling is enforced two ways:

1. **Structurally** — `answer` makes the planner call once, the exploratory synthesise once, and the refinement synthesise at most once. There is no loop that can issue a fourth call.
2. **Defensively** — every LLM stage is recorded in an `_LlmBudget` counter that asserts the total never exceeds `_MAX_LLM_CALLS` (3). A logic regression attempting a fourth call fails loudly.

### Pipeline stages

```
plan
 └─ retrieve (vector + keyword → RRF fusion)
      ├─ empty? → broaden plan, retrieve once → still empty? → "no matches" (no LLM call)
      └─ synthesise (exploratory)
           └─ NeedsMore AND refinement budget remains (SEARCH_MAX_REFINEMENTS)?
                → adjust plan, retrieve again, MERGE results
                → synthesise (final)  ← must answer or explicitly say "not found"
```

### Stage 1 — Planner (`search/planner.py`)

One LLM call (`SEARCH_PLANNER_MODEL`, default `gpt-5.4-mini` / `gemma3:12b`). Structured JSON output, parsed manually into a frozen `QueryPlan` dataclass — no Pydantic in the pipeline:

```python
QueryPlan(
    semantic_queries: list[str],          # 1–3 rephrasings → vector search
    keyword_terms: list[str],             # exact terms / IDs / names → FTS5
    filter_candidates: FilterCandidates,  # free-text correspondent/type/tag/date guesses
    sub_questions: list[str],
)
```

**Filters are resolved in code, not in the prompt.** The planner emits free-text filter candidates ("npower", "invoice"). `SearchCore` resolves each against the live `taxonomy` table (exact, then normalised match) and drops anything that does not resolve. This makes "the planner cannot apply a hallucinated filter" a code guarantee, and keeps the planner prompt small — it is never fed the full taxonomy list. UI-set filters are authoritative and bypass resolution. Date ranges are resolved against today's date.

### Stage 2 — Retriever (`search/retriever.py`)

For each `semantic_query` and `sub_question`:

1. Embed the query using the same embedding model as the indexed documents (via `EmbeddingClient`).
2. `StoreReader.vector_search` — exact cosine-distance KNN over the SQL-filtered candidate set (`SEARCH_TOP_K` results).
3. `StoreReader.keyword_search` — FTS5 BM25 search over the same filtered set.

**Reciprocal Rank Fusion (RRF):** all ranked lists from vector and keyword searches are fused with `score = Σ 1 / (60 + rank)` (the constant 60 is `_RRF_K`). Fused chunks are grouped by document — a document's RRF score is its best chunk's fused score — and the top `SEARCH_TOP_K` documents are passed to synthesis, each carrying its top chunks as context.

No cross-encoder re-ranker. At the project's target scale (≤~50k chunks), brute-force exact KNN is single-digit milliseconds.

### Stage 3 — Synthesiser (`search/synthesizer.py`)

One LLM call (`SEARCH_ANSWER_MODEL`, default `gpt-5.4` / `gemma3:27b`). The question and retrieved chunks are passed together, each chunk labelled with its source document. Retrieved chunks are **untrusted input** — the prompt places them below an explicit delimiter and instructs the model to treat everything below as data, never as instructions (prompt-injection defence).

Structured output is a discriminated result — `Answered(answer, citations)` or `NeedsMore(adjustment)`.

### Refinement (`search/refinement.py`)

If the synthesiser returns `NeedsMore` and the refinement budget remains, `SearchCore` adjusts or broadens the query plan and retrieves once more, merging the new results with the original set. A final synthesise call produces the answer. `SEARCH_MAX_REFINEMENTS` defaults to 1; at most one refinement ever runs.

### Result shape

```python
SearchResult(
    answer: str,
    sources: list[SourceDocument],
    plan: QueryPlan,
    stats: SearchStats,         # llm_calls, latency_ms, refined
)

SourceDocument(
    document_id: int,
    title: str | None,
    correspondent: str | None,
    document_type: str | None,
    created: str | None,
    snippet: str,               # up to 280 chars from the best-matching chunk
    paperless_url: str,
    score: float,
)
```

`correspondent` and `document_type` names are resolved from the `taxonomy` table at query time.

---

## HTTP API (`search/api.py`)

FastAPI + uvicorn. Pydantic models validate requests and responses at this boundary only; explicit mapping functions convert to/from the pipeline's frozen dataclasses.

### Endpoints

| Endpoint | Auth | Purpose |
|:---|:---|:---|
| `POST /api/auth/login` | None | Exchange API key for a signed session cookie |
| `GET /api/healthz` | None | Liveness; 503 if index is not ready or corrupt |
| `POST /api/search` | Required | `{query, filters?}` → `SearchResult` |
| `GET /api/facets` | Required | Correspondents, document types, tags, date range |
| `GET /api/stats` | Required | Index size, last reconcile timestamp, embedding model |
| `POST /api/reconcile` | Required | Trigger an immediate reconciliation cycle (202 Accepted) |
| `GET /` and assets | None | Serve the built React SPA |
| `/mcp` | Bearer token | MCP streamable-HTTP ASGI app |

`StaticFiles` is mounted **only** at the built frontend directory (`web/dist`). The `/data` volume is under no served path; the index database is never web-reachable.

### Abuse protection

A global asyncio `Semaphore` (`SEARCH_MAX_CONCURRENT`, default 4) bounds in-flight `/api/search` work. Combined with the hard 3-LLM-call ceiling, this caps both per-request cost and aggregate cost on an exposed endpoint.

---

## MCP Endpoint (`search/mcp_server.py`)

The MCP server uses the `FastMCP` streamable-HTTP transport (an ASGI app mounted at `/mcp`). Two tools, both backed by `SearchCore`:

| Tool | Calls | Returns |
|:---|:---|:---|
| `search_documents(query, filters?)` | `core.retrieve()` | Ranked source documents with snippets and Paperless deep-links; no synthesised answer |
| `ask_documents(question, filters?)` | `core.answer()` | Full result including the synthesised answer |

`search_documents` saves one LLM call — the calling agent synthesises its own answer. `ask_documents` is appropriate when the agent wants a direct prose response.

An ASGI bearer-token middleware wraps the MCP app: every request must carry `Authorization: Bearer <SEARCH_API_KEY>`. A missing or invalid token returns HTTP 401 without reaching the MCP handler. The token is never logged.

---

## Authentication (`search/auth.py`)

`SEARCH_API_KEY` is **mandatory**. An unset or empty key is a fatal preflight error — the search server refuses to start. It never runs in an unauthenticated state.

Two authentication paths:

**Programmatic and MCP access** — present `Authorization: Bearer <SEARCH_API_KEY>`. Verified with `hmac.compare_digest` (constant-time comparison to prevent timing side channels).

**Web UI** — the SPA is served unauthenticated (there is no token yet). The browser shows a login screen; the user enters the key once. The SPA `POST`s it to `/api/auth/login`, which verifies it and sets a **stateless signed session cookie**:

- Cookie attributes: `HttpOnly`, `Secure`, `SameSite=Strict`, path `/`.
- Cookie value: `issued_at.ttl_seconds.signature` — URL-safe base64, URL-safe, no padding. The signature is HMAC-SHA256 of the `issued_at.ttl_seconds` payload keyed by `SEARCH_API_KEY`. Both the timestamp and the TTL are tamper-evident; expiry is enforced at verification time.
- Lifetime: `SEARCH_SESSION_TTL` seconds (default 604800 = 7 days).
- No server-side session store is needed.

The API key is **never shipped to the browser** — the SPA sends it once to `/api/auth/login` and immediately discards it; all subsequent requests use the cookie.

Every `/api/*` request except `login` and `healthz`, and every `/mcp` request, is accepted on **either** a valid bearer token **or** a valid, unexpired session cookie. The gate is `is_request_authenticated(bearer, cookie, settings)` in `search/auth.py`.

---

## React Web UI

The frontend (`web/`) is a React + Vite + TypeScript SPA, built in a Node stage of the multi-stage Dockerfile and copied into the final image. The server serves `web/dist` at `/`.

Key pages:

- **Login page** — handles the §7.3 key-exchange handshake; routes to the search page on success.
- **Search page** — `SearchBar` (query input) + `FilterControls` (populated from `/api/facets`) + `AnswerCard` (synthesised answer, clickable `[n]` citations) + `SourceList` of `SourceCard`s. A transparency line renders the `plan` and `stats` fields from `SearchResult`.

The SPA and the API ship inside the same image — there is no version drift and no API negotiation needed.

---

## Health States

`GET /api/healthz` is unauthenticated and is the Docker healthcheck endpoint.

| HTTP status | `status` field | Meaning |
|:---|:---|:---|
| 200 | `ok` | Schema present, reconciliation has run at least once, `PRAGMA quick_check` passed |
| 503 | `index-not-ready` | DB absent, or schema not yet applied, or reconciliation has never completed |
| 503 | `index-corrupt` | DB exists with schema and a reconcile timestamp, but `quick_check` failed |

The server never crash-loops on an absent or initialising index — it starts, serves `healthz`, and waits. `depends_on` in Docker Compose handles startup ordering.

For the corruption recovery runbook, see [Store — Corruption Recovery](store.md#corruption-recovery).

---

## File Index

| File | Purpose |
|:---|:---|
| `api.py` | FastAPI app — all HTTP endpoints, SPA static mount, uvicorn entry |
| `mcp_server.py` | MCP server — two tools over `SearchCore`, bearer-token middleware |
| `core.py` | `SearchCore` — orchestrates the bounded agentic pipeline |
| `planner.py` | `QueryPlanner` — one LLM call → `QueryPlan` |
| `retriever.py` | `Retriever` — vector + keyword searches, filter resolution, RRF fusion |
| `synthesizer.py` | `Synthesizer` — one LLM call → `Answered` or `NeedsMore` |
| `refinement.py` | `adjust_plan` / `broaden_plan` — plan mutation for the refinement step |
| `auth.py` | `verify_api_key`, `issue_session_token`, `is_request_authenticated` |
| `models.py` | Frozen dataclasses: `QueryPlan`, `SearchResult`, `SourceDocument`, `SearchStats`, `Answered`, `NeedsMore`, `RetrievedChunk` |
| `wire.py` | Pydantic request/response models and mapping functions (HTTP boundary only) |
| `prompts.py` | System prompts for the planner and synthesiser |
