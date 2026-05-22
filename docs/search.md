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
| `POST /api/setup` | First-run setup — create the first admin account |
| `POST /api/auth/login` | Username/password sign-in — sets the session cookie |
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
| `GET /api/setup/status` | None | `{ needed }` — is first-run setup still required? |
| `POST /api/setup` | Setup token | Create the first admin account; `409` once set up |
| `POST /api/auth/login` | None | `{username, password, remember}` → session cookie + `{user}` |
| `POST /api/auth/logout` | Session | Destroy the current session |
| `GET /api/auth/me` | Session | The current user and role; `401` if unauthenticated |
| `GET /api/users` | Admin | List user accounts |
| `POST /api/users` | Admin | Create a user account |
| `PATCH /api/users/{id}` | Admin | Edit role / status / display name / reset password |
| `DELETE /api/users/{id}` | Admin | Delete a user account |
| `GET /api/healthz` | None | Liveness; 503 if index is not ready or corrupt |
| `GET /api/stats/public` | None | Minimal splash counts — `{document_count, chunk_count}` |
| `POST /api/search` | Read-only+ | `{query, filters?}` → `SearchResult` |
| `GET /api/facets` | Read-only+ | Correspondents, document types, tags, date range |
| `GET /api/stats` | Read-only+ | Index size, last reconcile timestamp, embedding model |
| `POST /api/reconcile` | Member+ | Trigger an immediate reconciliation cycle (202 Accepted) |
| `GET /` and assets | None | Serve the built React SPA (with a deep-link catch-all) |
| `/mcp` | API key (`mcp` scope) / session | MCP streamable-HTTP ASGI app |

The SPA is served by a catch-all that returns `index.html` for client-router
deep links (`/login`, `/setup`) while leaving real assets and every `/api`
and `/mcp` path untouched. Static serving is rooted **only** at the built
frontend directory (`web/dist`); the `/data` volume is under no served path,
so the index and application databases are never web-reachable.

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

An ASGI bearer-token middleware wraps the MCP app: every request must carry either a `search_session` cookie (a signed-in human) or `Authorization: Bearer <api-key>` where the key holds the `mcp` scope. A missing or invalid credential returns HTTP 401 without reaching the MCP handler. Credentials are never logged.

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
opaque `search_session` cookie. The cookie is `HttpOnly`, `Secure`,
`SameSite=Strict`, `Path=/`; its `Max-Age` is seven days when "keep me signed
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

**RBAC.** Three roles rank `readonly` < `member` < `admin`. The dependency
`require_role(...)` raises `403` on an insufficient role; `require_admin` is
the common admin gate. Search, facets and stats require Read-only or above;
reconcile requires Member or above; user management requires Admin. Two
guards protect administration: a user cannot delete, suspend or demote
themselves, and the last remaining admin cannot be deleted, suspended or
demoted.

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
| `auth.py` | Bearer extraction, role ranking |
| `sessions.py` | Opaque session tokens, SHA-256 hashing, the DB-backed session lifecycle |
| `deps.py` | FastAPI auth dependencies — `get_current_user`, `require_role`, `require_admin` |
| `setup.py` | First-run setup token generation, comparison, and setup-mode detection |
| `account_routes.py` | The account `/api` router — setup, login/logout/me, user CRUD |
| `accounts.py` | The self and last-admin account guards |
| `models.py` | Frozen dataclasses: `QueryPlan`, `SearchResult`, `SourceDocument`, `SearchStats`, `Answered`, `NeedsMore`, `RetrievedChunk` |
| `wire.py` | Pydantic request/response models and mapping functions (HTTP boundary only) |
| `prompts.py` | System prompts for the planner and synthesiser |
