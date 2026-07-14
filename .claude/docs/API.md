<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# API

Served by one uvicorn process (`search.api:main`). Wire models (Pydantic) live **only** in `src/search/wire/`; the SPA mirrors them in `web/src/api/types/`. `/openapi.json`, `/docs` and `/redoc` are disabled.

## Facts

### REST — `/api/*`

| Method + path | Auth | Handler |
|---------------|------|---------|
| `GET /api/healthz` | public | `routes.py:268` |
| `GET /api/setup/status`, `POST /api/setup` | public (setup token) | `account_routes.py:102,109` |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | public / session | `account_routes.py:121,143,155` |
| `GET /api/stats/public` | public | `account_routes.py:163` |
| `POST /api/search` | readonly + `api` | `routes.py:285` |
| `POST /api/search/stream` (NDJSON) | readonly + `api` | `routes.py:349` |
| `GET /api/facets`, `GET /api/stats`, `GET /api/documents` | readonly + `api` | `routes.py:407,423,439` |
| `POST /api/reconcile` | member + `api` | `routes.py:474` |
| `GET /api/documents/{id}` | readonly + `api` | `document_routes/_documents.py:75` |
| `GET /api/documents/{id}/pdf`, `/thumb` | readonly + `api` | `document_routes/_proxy.py:102,116` |
| `GET /api/recent-searches` | readonly + `api` | `document_routes/_documents.py:99` |
| `PATCH /api/documents/{id}` | member + `api` | `document_routes/_documents.py:111` |
| `POST /api/documents/{id}/reclassify`, `/retranscribe` (202) | member + `api` | `document_routes/_documents.py:135,158` |
| `DELETE /api/documents/{id}` (204) | admin + `admin` scope | `document_routes/_documents.py:182` |
| `GET /api/correspondents`, `/api/document-types`, `/api/tags` | readonly + `api` | `document_routes/_taxonomy.py:56,91,126` |
| `POST` on the same three (201) | member + `api` | `document_routes/_taxonomy.py:72,107,142` |
| `GET /api/index/status`, `/activity`, `/failed` | readonly + `api` | `index_routes.py:78,85,92` |
| `POST /api/index/rebuild` | admin + `admin` scope | `index_routes.py:97` |
| `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test-connection` | admin + `admin` scope | `settings_routes.py:95,110,125` |
| `GET /api/users`, `POST /api/users` (201), `PATCH`/`DELETE /api/users/{id}` | admin + `admin` scope | `account_routes.py:168,177,186,199` |
| `GET`/`POST /api/api-keys`, `PATCH`/`DELETE /api/api-keys/{id}` | member + `admin` scope (owner rules apply) | `api_key_routes.py:85,93,102,112` |

Auth column = *role* + *key scope*. The scope half binds **API-key callers only**; a cookie session is bounded by role alone (`deps.py::_enforce` skips the scope check when `caller.scopes is None`). Roles rank `readonly` < `member` < `admin`.

Everything else (`GET /{path}`) is the SPA catch-all (`spa.py:69`), which hard-refuses paths starting with `api/` or `mcp`.

### MCP — `POST /mcp`

Streamable-HTTP FastMCP app attached as an **exact-path `Route`** (not a mount — a mount would double-prefix to `/mcp/mcp`). Auth: an active session cookie **or** an API key carrying the `mcp` scope; 401 otherwise.

| Tool | Bills LLM budget | Does |
|------|------------------|------|
| `semantic_search` | quota-checked (`bills_llm=True` in `_dispatch`) but makes **zero** chat calls — only the query embedding | Plan-free hybrid RAG (`SearchCore.retrieve`) |
| `keyword_search` | no | FTS / browse (`SearchCore.keyword_search`) — no LLM, no embedding |
| `fetch_documents` | no | Canonical full text from Paperless — **max 5 ids/call**, each capped at `FETCH_MAX_CHARS` (50 000, `core.py:127`) |
| `list_filters` | no | The filter catalogue with counts |
| `deep_search` | **yes** | The full agentic pipeline (`SearchCore.answer`) |

MCP tool results drop `stats.trace` (the verbose per-phase reasoning is an SPA-only affordance); `answer`, `sources`, `plan` and the `cost` summary are returned.

### Streaming (`POST /api/search/stream`)

NDJSON, one JSON object per line, built by `search/wire/stream.py`: `phase_start` / `phase_done` events, `result`, `error`. A bare `\n` keepalive is emitted every 15 s of silence (`_STREAM_KEEPALIVE_SECONDS`, `routes.py:91`) — **clients must skip blank lines**. Once the body has begun the request can no longer fail with an HTTP status: a budget breach becomes a `budget` frame, a mid-rebuild index an `index_not_ready` frame, anything else an `internal` frame. The quota pre-check therefore runs *before* the body starts, so an over-quota key still gets a clean 429.

### Status mapping

| Status | Raised for |
|--------|-----------|
| 401 | Missing/invalid session or API key |
| 403 | Insufficient role, or an API key missing the route's scope (`deps.py::_enforce`); suspended account and bad setup token (login/setup) |
| 404 | Unknown document/user/key — and, deliberately, a key the caller does not own (`api_key_routes.py:256,313`) |
| 409 | Setup already done, username taken, user-guard rejection (`account_routes.py`) — and a Paperless conflict |
| 422 | Wire-model validation (query ≤ `MAX_QUERY_LENGTH`, username 3–64, password ≥ 12 — `search/validation.py`) |
| 429 | Login lockout, or the per-key daily token quota (`Retry-After` = UTC midnight) |
| 502 | Paperless upstream 5xx or unreachable (`register_paperless_exception_handlers`, `api.py:274`) |
| 503 | Index not ready / corrupt (healthz, search), unwritable data dir on rebuild |

## Procedures

1. **Mint programmatic access** — sign in, `POST /api/api-keys` with the scopes you need (`api` for REST, `mcp` for the MCP endpoint, `admin` for settings/users). The raw `sk-pls-…` value is shown exactly once.
2. **Call the REST API** — `Authorization: Bearer sk-pls-…`. A key with only `mcp` scope cannot reach `/api/*`, and vice versa (regression-tested in `tests/integration/test_api_keys_rbac.py`).
3. **Add a route** — register it on a router **before** `register_spa(...)` (registration order is load-bearing: the SPA catch-all is `GET /{full_path:path}`), define its request/response models in `src/search/wire/`, mirror the types in `web/src/api/types/`, and add the client call under `web/src/api/client/`.

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Every `/mcp` request fails with `RuntimeError: Task group is not initialized` | An ASGI sub-app attached by Route/mount never gets its lifespan run by the parent | `create_app`'s lifespan must call `mcp_app.session_manager.run()` (`api.py:389`) |
| Bare `/mcp` 405s | `/mcp` was attached with `app.mount` (double prefix `/mcp/mcp`) | Attach it as an exact-path `Route` and leave FastMCP's `streamable_http_path` at its default |
| A new GET route 404s / returns index.html | It was registered *after* `register_spa` | Move its registration before the SPA |
| Client hangs parsing the stream | It treats the 15 s keepalive blank line as a frame | Skip blank lines |
| MCP requests 421 behind the proxy | FastMCP's DNS-rebinding check auto-enables a localhost-only allowlist | It is deliberately disabled (`TransportSecuritySettings(enable_dns_rebinding_protection=False)`); keep it so |

## Related

- [SECURITY](SECURITY.md) · [modules/search-api](modules/search-api.md) · [modules/search-pipeline](modules/search-pipeline.md) · [modules/web](modules/web.md)
- Human docs: `docs/search.md`
