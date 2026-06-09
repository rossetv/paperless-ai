# The Search Server

`src/search/` is the read side of the semantic-search subsystem. It exposes an agentic search pipeline over three surfaces — an HTTP JSON API, a React Web UI, and an MCP endpoint — all from a single process.

**Entry point:** `search.api:main` (CLI command: `paperless-search-server`)

The search server is **read-only**. It accesses the store exclusively through `StoreReader`, which has no write methods. The indexer daemon holds the sole write lock.

---

## Process Layout

One uvicorn process serves everything, composed from several routers (each in its own module) plus the MCP mount and the SPA:

| Router / mount | Surface |
|:---|:---|
| `routes.py` | Core search API: `healthz`, `search`, `facets`, `stats`, the Library browse (`GET /api/documents`), `reconcile` |
| `account_routes.py` | First-run setup, login/logout/me, the public splash stats, user CRUD |
| `settings_routes.py` | Read and update runtime config (`/api/settings`), connection test |
| `api_key_routes.py` | Mint, list, edit, and revoke API keys (`/api/api-keys`) |
| `document_routes/` | Single-document summary, metadata PATCH, delete, reclassify/retranscribe re-queue, taxonomy CRUD, and the PDF/thumbnail streaming proxy |
| `index_routes.py` | The Index operations dashboard: daemon status, reconcile activity, failed documents, and the destructive `rebuild` |
| `mcp_server.py` (`/mcp`) | MCP streamable-HTTP ASGI app — two tools |
| `spa.py` (`/`) | The built React SPA with a deep-link catch-all |

The MCP ASGI app and every `/api` router are mounted **before** the SPA catch-all, so they take precedence over static serving — no second process, no additional port.

Each request opens its own short-lived `app.db` connection (a `sqlite3.Connection` cannot be safely shared across the threads FastAPI serves on); the index `StoreReader` is a single shared instance. A daemon thread writes a periodic `daemon_status` heartbeat to `app.db` so the dashboard's "search" tile stays fresh.

---

## The Agentic Search Pipeline (`search/core.py`)

The pipeline is a pure library. `SearchCore` wires the planner, retriever, and synthesiser together. Two public entry points:

- `answer(query, ui_filters)` — full pipeline with synthesis. Used by `POST /api/search` and the MCP `ask_documents` tool.
- `retrieve(query, ui_filters)` — plan and retrieve only; no synthesis. Used by the MCP `search_documents` tool (the calling agent synthesises, saving one LLM call).

Every stage takes its LLM client and store reader by injection, so the pipeline is testable offline.

### Per-query LLM-call budget

The number of LLM chat calls per query is **`2 + SEARCH_MAX_REFINEMENTS`**: one planner call + one exploratory synthesise + one synthesise per refinement pass. There is no hard cap — the operator sets `SEARCH_MAX_REFINEMENTS` from the UI, so cost and latency scale linearly with it. The query embedding is not a chat call and is not counted.

The budget is enforced two ways:

1. **Structurally** — `answer` makes the planner call once, the exploratory synthesise once, then loops the refinement synthesise at most `SEARCH_MAX_REFINEMENTS` times; the loop counter bounds it.
2. **Defensively** — every LLM stage is recorded through an `_LlmBudget` counter, constructed per query with a limit of `2 + SEARCH_MAX_REFINEMENTS`, that raises `LlmBudgetExceededError` if the total would exceed it. A plain `raise` (not `assert`, which `python -O` would strip) means a logic regression attempting an extra call fails loudly on the billable endpoint. `SearchStats.llm_calls` reports calls *attempted*, which on a fully successful query equals calls billed.

Several optional knobs spend **fewer** calls without ever exceeding the ceiling: a result cache serves a repeated query with **zero** LLM calls; a degenerate or too-vague query is rejected before synthesis; a trivial keyword query can skip the planner; and an irrelevant retrieval skips synthesis entirely (see [Fail-fast gates](#fail-fast-gates) below).

### Pipeline stages

```
(result cache hit? → return, 0 LLM calls)
(query shorter than SEARCH_MIN_QUERY_CHARS? → "be more specific", 0 LLM calls)   ← Layer 0
plan  (skipped for a trivial query if SEARCH_SKIP_PLANNER_FOR_TRIVIAL)
 ├─ too vague? planner returns clarify (SEARCH_GATE_ADEQUACY) → "be more specific", no synth   ← Layer 1
 └─ retrieve (vector + keyword → RRF fusion)
      ├─ empty? → broaden plan (drop filters), retrieve once → still empty? → "no matches" (no synth call)
      ├─ irrelevant? best similarity < SEARCH_RELEVANCE_MIN_SIMILARITY AND no keyword hit (SEARCH_GATE_RELEVANCE) → "no matches"   ← Layer 2
      └─ synthesise (exploratory)
           └─ loop while NeedsMore, up to SEARCH_MAX_REFINEMENTS times (default 1):
                → adjust plan, retrieve again, MERGE results
                → synthesise (exploratory; the last allowed pass is final)
                                          ← final must answer or say "not found"
```

### Fail-fast gates

Three cheap checks short-circuit queries that cannot be answered well — cheapest first, each individually toggle-able:

- **Layer 0 — degenerate input** (`SEARCH_MIN_QUERY_CHARS`, default 2, no LLM call). A query that is empty or shorter than the floor after trimming returns a "be more specific" clarify outcome before anything runs.
- **Layer 1 — adequacy** (`SEARCH_GATE_ADEQUACY`, default on, no *extra* call). The planner's existing call returns *either* a `QueryPlan` *or* a `ClarifyNeeded`. A query too vague to search a personal library (a bare generic word, a name with no question) is sent back for clarification before retrieval.
- **Layer 2 — relevance** (`SEARCH_GATE_RELEVANCE` + `SEARCH_RELEVANCE_MIN_SIMILARITY`, default 0.60). After retrieval, if the best **absolute** vector similarity is below the floor **and** there is no keyword hit, synthesis is skipped and a "no matches" outcome is returned. Requiring *both* signals to fail is what keeps it conservative: an exact-term search is protected by its keyword hit, a strong semantic match by its vector signal.

All three are **recall-first**. Layer 1 errs toward producing a plan, and Layer 2 **fails open** — a similarity that cannot be read never causes a rejection. The floor is calibrated against the live index (good queries ≥ 0.666, off-topic ≈ 0.567), so it catches blatantly off-topic queries but deliberately leaves near-miss "I don't hold that specific document" cases to the synthesiser, which reads the documents and says so.

### Result cache

A successful answer is written to a process-local result cache keyed on the normalised query, the UI filters, and a cheap index-version signal (`document_count:chunk_count`). A cache hit makes zero LLM calls and returns the prior `SearchResult` directly. The cache is bypassed (fail-open) when the index version cannot be read, and a no-match or degraded result is never cached. A corpus change moves the index-version key and invalidates prior entries; a config change drops the cache singleton so the next query recomputes. `SEARCH_CACHE_TTL_SECONDS` of 0 disables it (default 14400 = 4 h).

### Stage 1 — Planner (`search/planner.py`)

One LLM call (`SEARCH_PLANNER_MODEL`, default `gpt-5.4-mini` / `gemma3:12b`). Structured JSON output, parsed manually into a frozen `QueryPlan` — or a `ClarifyNeeded`, when the adequacy gate (Layer 1) fires. No Pydantic in the pipeline:

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

One LLM call (`SEARCH_ANSWER_MODEL`, default `gpt-5.5` / `gemma3:27b`). The message is laid out **control plane first**: the question and instructions come first, then the retrieved chunks (each labelled with its source `[document_id]`) as untrusted data.

Retrieved chunks are **untrusted input** — a document can contain text that reads as an instruction. The prompt wraps the chunks in a data block fenced by an **unpredictable per-request nonce** (`<<<DATA {nonce}>>>` … `<<<END DATA {nonce}>>>`, built by `common.prompt_fences.build_data_fence`) and tells the model that everything between the two fences is data, never instructions. Because the nonce is a fresh random token per message, a chunk cannot reproduce the closing fence to break out of the data region — a stronger guarantee than the static delimiter it replaced.

Structured output is a discriminated result — `Answered(answer, citations)` or `NeedsMore(adjustment)`. `SearchResult.sources` is narrowed to the documents the answer actually **cited** (the frontend resolves each `[n]` marker by `document_id`); a citation-shy or degraded answer falls back to the full retrieved set rather than showing no sources.

### Refinement (`search/refinement.py`)

If the synthesiser returns `NeedsMore` and the refinement budget remains, `SearchCore` folds the adjustment hint into the query plan, retrieves again, and merges the new results with the accumulated set. This loops up to `SEARCH_MAX_REFINEMENTS` times: intermediate passes synthesise in exploratory mode (and may ask for more), and the last allowed pass runs in final mode (must answer or say "not found"), so the loop always terminates. `SEARCH_MAX_REFINEMENTS` defaults to 1 (one refinement), but the operator can set any number — each pass is one extra LLM call.

### Result shape

```python
SearchResult(
    answer: str,
    sources: list[SourceDocument],
    plan: QueryPlan,
    stats: SearchStats,         # llm_calls, latency_ms, refined
    outcome_kind: str,          # "answered" | "clarify" | "no_match" (fail-fast gates)
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

The "Auth" column maps to the FastAPI dependencies in `search/deps.py`: **None** (unauthenticated), **Session** (a signed-in cookie), **Read-only+** = `require_api_scope` (Read-only role or above; an API-key caller must also hold the `api` scope), **Member+** = `require_api_scope_member`, **Admin** = `require_admin` (admin role and, for keys, the `admin` scope).

| Endpoint | Auth | Purpose |
|:---|:---|:---|
| `GET /api/setup/status` | None | `{ needed }` — is first-run setup still required? |
| `POST /api/setup` | Setup token | Create the first admin account; `409` once set up |
| `POST /api/auth/login` | None | `{username, password, remember}` → session cookie + `{user}` |
| `POST /api/auth/logout` | Session | Destroy the current session |
| `GET /api/auth/me` | Session | The current user and role; `401` if unauthenticated |
| `GET /api/healthz` | None | Liveness; 503 if index is not ready or corrupt |
| `GET /api/stats/public` | None | Minimal splash counts — `{document_count, chunk_count}` |
| `POST /api/search` | Read-only+ | `{query, filters?}` → `SearchResult` |
| `GET /api/facets` | Read-only+ | Correspondents, document types, tags, date range |
| `GET /api/stats` | Read-only+ | Index size, last reconcile timestamp, embedding model |
| `GET /api/documents` | Read-only+ | Paginated Library browse (sort, text, filters) |
| `GET /api/documents/{id}` | Read-only+ | One document's summary |
| `GET /api/documents/{id}/pdf` · `…/thumb` | Read-only+ | Stream the PDF / thumbnail proxied from Paperless |
| `GET /api/recent-searches` | Read-only+ | The caller's own recent-search history |
| `PATCH /api/documents/{id}` | Member+ | Edit document metadata (forwarded to Paperless) |
| `POST /api/documents/{id}/reclassify` · `…/retranscribe` | Member+ | Re-queue for classification / OCR |
| `GET·POST /api/correspondents` · `/document-types` · `/tags` | Read-only+ (GET) / Member+ (POST) | Taxonomy list and create |
| `DELETE /api/documents/{id}` | Admin | Delete the document from Paperless |
| `POST /api/reconcile` | Member+ | Trigger an immediate reconciliation cycle (202 Accepted) |
| `GET·PUT /api/settings`, `POST /api/settings/test-connection` | Read-only+ (GET) / Admin (PUT) | Read and update runtime config |
| `GET·POST·PATCH·DELETE /api/api-keys[/{id}]` | Session / owner / Admin | Mint, list, edit, revoke API keys |
| `GET /api/users` · `POST` · `PATCH /{id}` · `DELETE /{id}` | Admin | User account CRUD |
| `GET /api/index/{status,activity,failed}` | Read-only+ | The Index operations dashboard |
| `POST /api/index/rebuild` | Admin | Wipe and re-index the whole archive (202 Accepted) |
| `GET /` and assets | None | Serve the built React SPA (with a deep-link catch-all) |
| `/mcp` | API key (`mcp` scope) / session | MCP streamable-HTTP ASGI app |

The `POST /api/search` handler resolves the `SearchCore` **per request** (a cheap one-row `SELECT` on `app.db`, rebuilding the config-derived component graph only when `config_version` has changed), so a saved configuration change — answer model, top-k, prompts, concurrency cap — takes effect on the next query with no restart. A successful search by an authenticated caller is recorded in that caller's recent-search history.

The SPA is served by a catch-all that returns `index.html` for client-router deep links (`/login`, `/setup`) while leaving real assets and every `/api` and `/mcp` path untouched. Static serving is rooted **only** at the built frontend directory (`web/dist`); the `/data` volume is under no served path, so the index and application databases are never web-reachable. Any `httpx` error escaping a Paperless-proxying route is mapped to a meaningful status (404/409/502) by a centralised exception handler rather than leaking a 500.

### Keeping the event loop free, and abuse protection

The store, the LLM client, and the per-request SQLite connections all do **blocking** I/O. Both the FastAPI routes and the MCP layer run that work off the event loop through one shared helper, `run_blocking` (`search/offload.py`), which dispatches the call to the loop's default executor. This includes the document routes — every `StoreReader`, Paperless, and PDF/thumbnail call in `search/document_routes/` is awaited through `run_blocking`, so a slow upstream never stalls the single loop and serialises every concurrent caller behind it.

A `LazySemaphore` (also in `offload.py`) bounds in-flight `/api/search` work to `SEARCH_MAX_CONCURRENT` (default 4); the MCP tools share the same primitive with the same ceiling. The semaphore is created lazily on first use (so it binds to the serving loop) and is hot-reloadable — a changed cap takes effect on the next request. A ceiling of 0 means unbounded. Combined with the per-query LLM-call budget (`2 + SEARCH_MAX_REFINEMENTS`), this bounds aggregate cost on an exposed, billable endpoint — though raising `SEARCH_MAX_REFINEMENTS` raises the per-request cost.

A separate per-username login throttle (`search/login_throttle.py`) bounds password-guessing attempts on `POST /api/auth/login`.

---

## MCP Endpoint (`search/mcp_server.py`)

The MCP server uses the `FastMCP` streamable-HTTP transport (an ASGI app mounted at `/mcp`). Two tools, both backed by `SearchCore`:

| Tool | Calls | Returns |
|:---|:---|:---|
| `search_documents(query, filters?)` | `core.retrieve()` | Ranked source documents with snippets and Paperless deep-links; no synthesised answer |
| `ask_documents(question, filters?)` | `core.answer()` | Full result including the synthesised answer |

`search_documents` saves one LLM call — the calling agent synthesises its own answer. `ask_documents` is appropriate when the agent wants a direct prose response. Both tool bodies are dispatched through `run_blocking` under a shared `LazySemaphore` (the same `SEARCH_MAX_CONCURRENT` bound as `/api/search`) — FastMCP 1.27 would otherwise run a sync tool directly on the loop, freezing the co-mounted REST API for the tool's multi-second, LLM-bound duration. The query is normalised at the boundary (trimmed, non-empty, length-bounded); any core failure is logged server-side with its traceback and returned to the client as a sanitised error carrying no internal detail.

An ASGI bearer-token middleware wraps the MCP app: every request must carry either a `search_session` cookie (a signed-in human) or `Authorization: Bearer <api-key>` where the key holds the `mcp` scope. A missing or invalid credential returns HTTP 401 without reaching the MCP handler. The middleware opens a fresh `app.db` connection per request (off the loop, via `run_blocking`); a successful cookie auth also refreshes `last_seen_at`. Credentials are never logged — a rejection records only whether a header or cookie was present.

---

## Authentication (`search/auth.py`, `search/sessions.py`, `search/deps.py`)

Authentication is **database-backed user accounts** with role-based access
control. Accounts and sessions live in `app.db` (`APP_DB_PATH`), separate
from the search index.

**First-run setup.** When `app.db` has no users, the server enters *setup
mode*: it generates a one-off setup token, logs it to the container
(`SETUP TOKEN: … — open /setup to create the first admin`), and `POST /api/setup`
— guarded by a constant-time comparison of that token — creates the first
admin. Once any user exists, `/api/setup` returns `409`.

**Sign-in.** `POST /api/auth/login` verifies the username and password
(argon2id) and, on success, inserts a row in the `sessions` table and sets an
opaque `search_session` cookie. The cookie is `HttpOnly`, `SameSite=Strict`,
`Path=/`, and `Secure` over HTTPS (the flag is set when `request.url.scheme`
is `https` — correct behind the documented proxy that runs uvicorn with
`proxy_headers=True`); its `Max-Age` is seven days when "keep me signed
in" is ticked, eight hours otherwise. The database stores only the SHA-256 of
the token — the raw token is never persisted. `SameSite=Strict` is the CSRF
defence; no separate CSRF token is needed.

**Every request.** `get_current_user` hashes the cookie token, looks the
session up, checks expiry, loads the user and checks the account is active.
`last_seen_at` is refreshed at most once every ~5 minutes, so authentication
is not a database write per request. `POST /api/auth/logout` deletes the
session row; suspending or deleting a user deletes **all** that user's
sessions, so access is revoked instantly — the key advantage of server-side
sessions over a stateless token.

**RBAC.** Three roles rank `readonly` < `member` < `admin`. The dependencies
`require_api_scope` (Read-only+) and `require_api_scope_member` (Member+) raise
`403` on an insufficient role, and additionally require the `api` scope when the
caller is an API key; `require_admin` is the admin gate (admin role and, for
keys, the `admin` scope). Search, facets, stats and browse require Read-only or
above; reconcile, metadata edits and re-queues require Member or above; user
management, settings writes and rebuild require Admin. Two guards protect
administration: a user cannot delete, suspend or demote themselves, and the last
remaining admin cannot be deleted, suspended or demoted.

**API keys.** Programmatic and MCP access uses **API keys** minted in the web
UI (Settings → API Keys), not a shared secret. A key looks like
`sk-pls-<random>`; the full key is shown **once** at creation and is
unrecoverable afterwards — only its SHA-256 hash and a short display prefix
(`sk-pls-XXXXX`) are stored.

Each key carries **scopes**: `api` (the REST data routes), `mcp` (the `/mcp`
surface), `admin` (user and key administration). A request is authorised only
if the presented key holds the required scope. A key's reach is also bounded
by its **owner's role** — a key never exceeds what its owner could do directly.

A key can be given an **expiry** and can be **revoked** at any time; revocation
takes effect immediately. The owner can **edit** it — rename it, change its
scopes, or change its expiry — at any time. Editing is owner-only: an admin
may view and revoke other users' keys but not edit them.

**`SEARCH_API_KEY` is retired.** The `SEARCH_API_KEY` environment variable is
no longer read by the search server (Wave 3). A fresh install has no
programmatic or MCP access until an account is created and a key is minted —
there is no default credential.

---

## React Web UI

The frontend (`web/`) is a React + Vite + TypeScript SPA, built in a Node stage of the multi-stage Dockerfile and copied into the final image. The server serves `web/dist` at `/`. It is structured as a strict layer stack (`components/` → `features/` → `pages/`) with all design values in `tokens.css` — see `CODE_GUIDELINES.md` §12. All API state goes through the typed `web/src/api/` layer, which sends `credentials: 'include'` so the `HttpOnly` session cookie carries authentication; the JS bundle never sees a credential.

Representative pages:

- **Setup / Login** — first-run setup against the printed token, then plain username/password sign-in that sets the session cookie (no client-side key handling).
- **Search** — `SearchBar` + `FilterControls` (populated from `/api/facets`) + `AnswerCard` (synthesised answer, clickable `[n]` citations) + `SourceList` of `SourceCard`s, with a transparency line rendering the `plan` and `stats` from `SearchResult`.
- **Library** — paginated document browse (`/api/documents`) with a document detail view (summary, PDF/thumbnail proxy, reclassify/retranscribe/delete).
- **Settings** — runtime config and connection test; **API Keys**; **Users**; and the **Index** operations dashboard (daemon status, reconcile activity, failed documents, rebuild).

The SPA and the API ship inside the same image — there is no version drift and no API negotiation needed.

---

## Health States

`GET /api/healthz` is unauthenticated and is the Docker healthcheck endpoint. The three-state verdict is computed by `evaluate_index_health` in `search/routes.py` (the file check plus a `get_stats` and a `quick_check`, run off the loop):

| HTTP status | `status` field | Meaning |
|:---|:---|:---|
| 200 | `ok` | Schema present, reconciliation has run at least once, `PRAGMA quick_check` passed |
| 503 | `index-not-ready` | DB absent, or schema not yet applied (surfaced as `SchemaNotReadyError`), or reconciliation has never completed |
| 503 | `index-corrupt` | DB exists with schema and a reconcile timestamp, but `quick_check` failed |

The handler never raises — any unexpected error becomes a clean 503. The server never crash-loops on an absent or initialising index — it starts, serves `healthz`, and waits. `depends_on` in Docker Compose handles startup ordering.

For the corruption recovery runbook, see [Store — Corruption Recovery](store.md#corruption-recovery).

---

## File Index

**Pipeline (pure library).**

| File | Purpose |
|:---|:---|
| `core.py` | `SearchCore` — orchestrates the bounded agentic pipeline, the three fail-fast gates, `_LlmBudget`, result-cache wiring |
| `planner.py` | `QueryPlanner` — one LLM call → `QueryPlan` or `ClarifyNeeded` (Layer 1) |
| `retriever.py` | `Retriever` — vector + keyword searches, filter resolution, RRF fusion (`_RRF_K = 60`), `RetrievalSignal` |
| `synthesizer.py` | `Synthesizer` — one LLM call → `Answered` or `NeedsMore` |
| `refinement.py` | `adjust_plan` / `broaden_plan` / `merge_chunks` — plan mutation and chunk merging |
| `sources.py` | `assemble_sources` — fuse chunks into `SourceDocument`s with resolved names and deep-links |
| `cache.py` | The process-local result cache and its index-version key |
| `text.py` | Query-normalisation and trivial-query helpers |
| `models.py` | Frozen dataclasses: `QueryPlan`, `FilterCandidates`, `RetrievedChunk`, `SourceDocument`, `SearchStats`, `SearchResult`, `Answered`, `NeedsMore`, `ClarifyNeeded`, `RetrievalSignal` (and the `PlanOutcome` alias) |
| `prompts.py` | System prompts and the per-request nonce data-fence layout |
| `errors.py` | `SearchError` / `LlmBudgetExceededError` |

**Interfaces and HTTP plumbing.**

| File | Purpose |
|:---|:---|
| `api.py` | FastAPI app factory — router/MCP/SPA wiring, per-request core cache, uvicorn entry |
| `routes.py` | Core `/api` router: search, facets, stats, browse, reconcile, healthz |
| `account_routes.py` · `accounts.py` | Setup, login/logout/me, public stats, user CRUD; the self / last-admin guards |
| `settings_routes.py` · `settings_service.py` | Read/update runtime config and connection test |
| `api_key_routes.py` | Mint / list / edit / revoke API keys |
| `document_routes/` | `_documents` (summary, PATCH, delete, re-queue), `_taxonomy` (CRUD), `_proxy` (PDF/thumb) |
| `index_routes.py` · `index_service.py` | The Index operations dashboard and `rebuild` |
| `mcp_server.py` | MCP server — two tools over `SearchCore`, bearer-token middleware |
| `spa.py` | SPA static mount with the deep-link catch-all |
| `wire/` | Pydantic request/response models and mapping functions (HTTP boundary only) |
| `offload.py` | `run_blocking` (event-loop offload) and `LazySemaphore` (concurrency bound) |

**Auth.**

| File | Purpose |
|:---|:---|
| `auth.py` | Bearer extraction, role ranking, the session-cookie name |
| `sessions.py` | Opaque session tokens, SHA-256 hashing, the DB-backed session lifecycle |
| `api_keys.py` | API-key scopes, hashing, and resolution |
| `deps.py` | FastAPI dependencies — `get_current_user`, `require_api_scope`, `require_api_scope_member`, `require_admin`, `get_app_db` |
| `setup.py` | First-run setup token generation, comparison, and setup-mode detection |
| `login_throttle.py` | Per-username login-attempt throttle |
| `cookies.py` | Session-cookie attributes (`HttpOnly`, `Secure`, `SameSite=Strict`) |
