<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../INDEX.md)

# Security

## Facts

### Authentication

| Credential | Shape | Storage | Source |
|-----------|-------|---------|--------|
| Session cookie | `search_session`, `secrets.token_urlsafe(32)`; HttpOnly + `SameSite=Strict` + `Secure` when `request.url.scheme == "https"` | `sha256(token)` only, in `app.db` `sessions.token_hash` | `src/search/sessions.py` (`_TOKEN_BYTES`, `new_token`) · `src/search/cookies.py` (`set_session_cookie`) · `src/search/auth.py` (`SESSION_COOKIE_NAME`) |
| API key | `sk-pls-` + `token_urlsafe(32)`; returned **once** on create; 12-char display prefix kept for the UI | `sha256(key)` only, in `app.db` `api_keys.key_hash` | `src/search/api_keys.py` (`RAW_KEY_PREFIX`, `_KEY_BODY_BYTES`, `KEY_PREFIX_LENGTH`) |
| Password | argon2id, `PasswordHasher()` library defaults | Encoded hash in `app.db` `users.password_hash` | `src/appdb/passwords.py` (`_HASHER`) |
| Setup token | `token_urlsafe(24)`, **memory-only** (`SetupState`), compared with `hmac.compare_digest`; logged once at WARNING at startup when `users` is empty | never persisted | `src/search/setup.py` (`generate_setup_token`, `is_setup_needed`) · `src/search/api.py` (`search.setup_mode` warning) |

SHA-256 (not a slow KDF) is correct for sessions and API keys — both are full-entropy random values, not user-chosen secrets. The legacy shared `SEARCH_API_KEY` is retired (absent from `src/common/config/_catalogue.py`): a fresh install has zero programmatic access until a key is minted.

### Authorisation

Roles rank `readonly`(0) < `member`(1) < `admin`(2); an unknown role **and** an unknown requirement both rank −1 and are refused — fail closed (`src/search/auth.py`, `_ROLE_RANK` / `authorise_role`). Scopes are `api` / `mcp` / `admin` (`src/search/api_keys.py`, `SCOPE_API` / `SCOPE_MCP` / `SCOPE_ADMIN`); a key is bounded by **both** its scopes and its owner's *current* role — it can never exceed the owner (`src/search/deps.py`, `_enforce`).

| Gate | Role | Key scope | Routes |
|------|------|-----------|--------|
| none (public) | — | — | `/api/healthz`, `/api/setup`, `/api/setup/status`, `/api/auth/login`, `/api/stats/public` |
| `require_api_scope` (`deps.py`) | readonly | `api` | search, search/stream, facets, stats, documents browse + detail, `/pdf`, `/thumb`, recent-searches, taxonomy GET, index status/activity/failed |
| `require_api_scope_member` (`deps.py`) | member | `api` | reconcile, document PATCH, reclassify, retranscribe, taxonomy POST |
| `require_admin` (`deps.py`) | admin | `admin` | document DELETE, user CRUD, settings GET/PUT/test-connection, index rebuild |
| `require_key_management` (`deps.py`) | member (admin lists all keys) | `admin` | `/api/api-keys` CRUD |
| MCP ASGI middleware (`src/search/mcp_server.py`, `_BearerAuthMiddleware`) | any active session **or** a key with `mcp` scope | `mcp` (key callers) | `/mcp` |

- **Account guards** (`src/search/accounts.py`): no self-delete/self-suspend/self-demote; never zero active admins. `apply_guarded_delete` / `apply_guarded_update` run the guard read and the write inside one `BEGIN IMMEDIATE` (`src/appdb/connection.py`, `transaction`), so the invariant is race-free.
- **Enumeration defence** (`src/search/api_key_routes.py::_update_api_key`, `::_delete_api_key`): `PATCH /api/api-keys/{id}` returns **404** (not 403) to a non-owner, even an admin; DELETE returns 404 to a non-owning non-admin.

### Anti-abuse

| Control | Value | Source |
|---------|-------|--------|
| Login throttle | 5 failures per (client IP, username) or **20 per username** (IP-independent) in a 900 s window ⇒ 900 s lockout, checked before any argon2 work; 4096 tracked keys max | `src/search/login_throttle.py` (`_MAX_FAILURES_BEFORE_LOCKOUT`, `_MAX_FAILURES_PER_USERNAME`, `_FAILURE_WINDOW_SECONDS`, `_LOCKOUT_SECONDS`, `_MAX_TRACKED_KEYS`) · `src/search/account_routes.py` (`_login`) |
| Timing | An unknown username still verifies against a fixed dummy hash | `src/search/passwords_login.py` (`_DUMMY_HASH`, `authenticate`) |
| Per-key daily token quota | `SEARCH_KEY_DAILY_TOKEN_QUOTA` (0 = off); over quota ⇒ 429 + `Retry-After` to UTC midnight. Soft cap (check → run → record) | `src/search/spend_quota.py::check_quota`, `::record_usage` |
| Concurrency ceilings | `SEARCH_MAX_CONCURRENT` (one shared ceiling for HTTP + MCP), `LLM_MAX_CONCURRENT` | `src/search/offload.py::LazySemaphore` · `src/common/concurrency.py::ConcurrencyGuard` |
| Query length | 4000 chars max, trimmed, empty rejected — one rule at both the REST and MCP boundaries | `src/search/wire/search.py` (`MAX_QUERY_LENGTH`) |

### Injection defences

- **Prompt injection** — untrusted document text enters an LLM prompt only inside the *user* message, wrapped in a fresh per-request 16-byte nonce fence (`common.prompt_fences.build_data_fence`, `src/common/prompt_fences.py` (`_FENCE_NONCE_BYTES`)). The system prompt describes the fence form generically and never carries the nonce (`src/search/prompts.py` (`SYNTHESISER_SYSTEM_PROMPT`)). Never a static delimiter, never a cached fence. Display names flowing into prompts are sanitised (`src/search/identity.py` (`sanitise_display_name`)).
- **SQL injection** — only `?` placeholders bind values. Interpolation is confined to non-value fragments, each carrying a `# nosec B608` with provenance: the *count* of placeholders (`src/store/_sql.py` (`placeholders`)), identifier whitelists (`_SORT_COLUMNS`, `src/store/reader/_browse.py`; the `_USER_COLUMNS` / `_SESSION_COLUMNS` constants in `src/appdb/`), and fixed clause fragments (`src/store/reader/_filters.py::build_filters`; the `col = ?` assignment lists in `src/appdb/users.py` (`update`), `src/appdb/api_keys.py` (`update`)). FTS terms are escaped (`escape_fts_term`, `src/store/reader/_filters.py`) and re-quoted as a literal phrase by the caller (`src/store/reader/_ranked.py`, `keyword_search` / `keyword_document_search`).
- **Stored XSS via proxied files** (`src/search/document_routes/_proxy.py`, `_PDF_RESPONSE_HEADERS` / `_THUMB_RESPONSE_HEADERS`) — `GET /api/documents/{id}/pdf` pins `Content-Type: application/pdf` (never forwards the upstream type); `/thumb` forwards only a 4-entry image allowlist (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) and otherwise 502s. Both send `nosniff`. Do not "fix" these by passing the upstream type through.
- **LLM output** — non-string scalars from the model are coerced to `""` before they can enter the taxonomy (`src/classifier/result.py` (`get_str`)); implausible dates (before 1900-01-01 or more than 366 days ahead) are dropped (`src/classifier/metadata.py` (`_DATE_FLOOR`, `_DATE_FUTURE_DAYS`)).

### Transport & headers

`SecurityHeadersMiddleware` (`src/search/security_headers.py`, `_SECURITY_HEADERS` / `_CONTENT_SECURITY_POLICY`) stamps `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, HSTS (`max-age=31536000; includeSubDomains`) and a CSP (`default-src 'self'`, `script-src 'self' 'unsafe-inline'`, `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:`, `font-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'self'`, `object-src 'none'`). It is **additive** — a header a handler already set is left alone, which is how the PDF/thumb proxy relaxes framing to `X-Frame-Options: SAMEORIGIN` + `frame-ancestors 'self'` for the in-app viewer. `'unsafe-inline'` exists for the single pre-paint theme script in `web/index.html` (the inline theme-bootstrap `<script>`); `'unsafe-eval'` is deliberately withheld. `/openapi.json`, `/docs` and `/redoc` are disabled (`src/search/api.py`, the `FastAPI(…)` constructor with `docs_url=None`/`redoc_url=None`/`openapi_url=None`).

CSRF defence is the `SameSite=Strict` cookie — there is no CSRF token (`src/search/sessions.py`, module docstring; `src/search/cookies.py`, `set_session_cookie`).

### Supply chain & runtime

| Gate | Command / fact | Source |
|------|----------------|--------|
| Static analysis | `bandit -r src/ -ll -f txt` (MEDIUM+) | `.github/workflows/ci.yml` (`security-scan`) |
| Python deps | `pip-audit` | `.github/workflows/ci.yml` (`dependency-audit`) |
| JS deps | `npm audit --omit=dev --audit-level=high` | `.github/workflows/ci.yml` (`frontend`) |
| Image build | gated on every check job, not just tests | `.github/workflows/ci.yml` (`docker` `needs:`) |
| Transitive pins | `overrides`: `handlebars`, `uuid`, `esbuild`, `js-yaml` | `web/package.json` (`overrides`) |
| Runtime container | non-root `appuser`; wheels installed offline (`pip install --no-index --find-links=/app/wheels`), so the runtime has no PyPI access and no compiler (`build-essential` is builder-stage only) | `Dockerfile` (`adduser --system --ingroup appgroup appuser`, `USER appuser`, `pip install --no-cache-dir --no-index --find-links=/app/wheels`) |

## Procedures

1. **Rotate a leaked API key** — revoke it (`DELETE /api/api-keys/{id}`; soft delete sets `revoked_at`, keeping usage history) and mint a new one; the raw key is unrecoverable by design.
2. **Lock down the proxy** — set `SEARCH_FORWARDED_ALLOW_IPS` to the reverse-proxy IP or CIDR (uvicorn 0.47 accepts both) whenever the uvicorn port is reachable directly.
3. **Reveal a stored secret** (admin, audited) — `GET /api/settings?reveal=true`; the revealed *keys* are logged as `search.settings_revealed` with the actor's username, never the values (`src/search/settings_routes.py`, `_read_settings`).

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Forged client IP in `sessions.ip`, or a cookie missing `Secure` | `SEARCH_FORWARDED_ALLOW_IPS` defaults to `*` (`src/common/config/_settings.py`, `SEARCH_FORWARDED_ALLOW_IPS`), so `X-Forwarded-For`/`-Proto` are trusted from any peer — safe only while the uvicorn port is proxy-only | Pin the setting to the proxy IP/CIDR |
| Lockout leniency in a multi-instance deployment | The login throttle, the result cache (`src/search/cache.py`), the core cache (`src/search/api.py`, `_CORE_CACHE` / `_resolve_search_core`) and the setup token are **process-local** singletons; the architecture assumes one search-server process | Run one search server, or accept N× leniency |
| SPA breaks under CSP after adding a dependency | A new library uses `eval`/`new Function` (blocked) or a second inline `<script>` appears in `index.html` | Remove the eval-using dependency; keep exactly one inline script |
| In-app PDF viewer goes blank | The security middleware was changed to overwrite (rather than skip) headers a handler set | Keep it additive |
| A legitimately redacted or refusal-quoting document is error-tagged | The document-level content gate (`is_error_content`, `src/common/content_checks.py` (`is_error_content`), called from the `is_error_content(...)` guard in `src/ocr/worker.py` and `src/classifier/quality_gates.py`) has **no** length threshold, unlike the OCR provider's 200-char refusal-dominance rule (`src/ocr/provider.py` (`_REFUSAL_DOMINANCE_THRESHOLD_CHARS`)) | Known asymmetry — expect false positives on denial letters / redacted bodies |

## Related

- [ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [CONFIGURATION](CONFIGURATION.md) · [modules/search-api](modules/search-api.md)
- The law: `CODE_GUIDELINES.md` §10 (Security)
