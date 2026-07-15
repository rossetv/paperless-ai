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
| Session cookie | `search_session`, `secrets.token_urlsafe(32)`; HttpOnly + `SameSite=Strict` + `Secure` when `request.url.scheme == "https"` | `sha256(token)` only, in `app.db` `sessions.token_hash` | `src/search/sessions.py:37,77` · `src/search/cookies.py:57-59` · `src/search/auth.py:40` |
| API key | `sk-pls-` + `token_urlsafe(32)`; returned **once** on create; 12-char display prefix kept for the UI | `sha256(key)` only, in `app.db` `api_keys.key_hash` | `src/search/api_keys.py:38,42,47` |
| Password | argon2id, `PasswordHasher()` library defaults | Encoded hash in `app.db` `users.password_hash` | `src/appdb/passwords.py:27` |
| Setup token | `token_urlsafe(24)`, **memory-only** (`SetupState`), compared with `hmac.compare_digest`; logged once at WARNING at startup when `users` is empty | never persisted | `src/search/setup.py:32,60-77` · `src/search/api.py:417-427` |

SHA-256 (not a slow KDF) is correct for sessions and API keys — both are full-entropy random values, not user-chosen secrets. The legacy shared `SEARCH_API_KEY` is retired (absent from `src/common/config/_catalogue.py`): a fresh install has zero programmatic access until a key is minted.

### Authorisation

Roles rank `readonly`(0) < `member`(1) < `admin`(2); an unknown role **and** an unknown requirement both rank −1 and are refused — fail closed (`src/search/auth.py:48-127`). Scopes are `api` / `mcp` / `admin` (`src/search/api_keys.py:52-54`); a key is bounded by **both** its scopes and its owner's *current* role — it can never exceed the owner (`src/search/deps.py:192-231`).

| Gate | Role | Key scope | Routes |
|------|------|-----------|--------|
| none (public) | — | — | `/api/healthz`, `/api/setup`, `/api/setup/status`, `/api/auth/login`, `/api/stats/public` |
| `require_api_scope` (`deps.py:292`) | readonly | `api` | search, search/stream, facets, stats, documents browse + detail, `/pdf`, `/thumb`, recent-searches, taxonomy GET, index status/activity/failed |
| `require_api_scope_member` (`deps.py:316`) | member | `api` | reconcile, document PATCH, reclassify, retranscribe, taxonomy POST |
| `require_admin` (`deps.py:270`) | admin | `admin` | document DELETE, user CRUD, settings GET/PUT/test-connection, index rebuild |
| `require_key_management` (`deps.py:360`) | member (admin lists all keys) | `admin` | `/api/api-keys` CRUD |
| MCP ASGI middleware (`src/search/mcp_server.py:112`) | any active session **or** a key with `mcp` scope | `mcp` (key callers) | `/mcp` |

- **Account guards** (`src/search/accounts.py`): no self-delete/self-suspend/self-demote; never zero active admins. `apply_guarded_delete` / `apply_guarded_update` run the guard read and the write inside one `BEGIN IMMEDIATE` (`src/appdb/connection.py:108`), so the invariant is race-free.
- **Enumeration defence** (`src/search/api_key_routes.py::_update_api_key`, `::_delete_api_key`): `PATCH /api/api-keys/{id}` returns **404** (not 403) to a non-owner, even an admin; DELETE returns 404 to a non-owning non-admin.

### Anti-abuse

| Control | Value | Source |
|---------|-------|--------|
| Login throttle | 5 failures per (client IP, username) or **20 per username** (IP-independent) in a 900 s window ⇒ 900 s lockout, checked before any argon2 work; 4096 tracked keys max | `src/search/login_throttle.py:72,79,83,86,90` · `src/search/account_routes.py:277-296` |
| Timing | An unknown username still verifies against a fixed dummy hash | `src/search/passwords_login.py:28,48-52` |
| Per-key daily token quota | `SEARCH_KEY_DAILY_TOKEN_QUOTA` (0 = off); over quota ⇒ 429 + `Retry-After` to UTC midnight. Soft cap (check → run → record) | `src/search/spend_quota.py::check_quota`, `::record_usage` |
| Concurrency ceilings | `SEARCH_MAX_CONCURRENT` (one shared ceiling for HTTP + MCP), `LLM_MAX_CONCURRENT` | `src/search/offload.py::LazySemaphore` · `src/common/concurrency.py::ConcurrencyGuard` |
| Query length | 4000 chars max, trimmed, empty rejected — one rule at both the REST and MCP boundaries | `src/search/wire/search.py:29` |

### Injection defences

- **Prompt injection** — untrusted document text enters an LLM prompt only inside the *user* message, wrapped in a fresh per-request 16-byte nonce fence (`common.prompt_fences.build_data_fence`, `src/common/prompt_fences.py:32`). The system prompt describes the fence form generically and never carries the nonce (`src/search/prompts.py:547-575`). Never a static delimiter, never a cached fence. Display names flowing into prompts are sanitised (`src/search/identity.py:29`).
- **SQL injection** — only `?` placeholders bind values. Interpolation is confined to non-value fragments, each carrying a `# nosec B608` with provenance: the *count* of placeholders (`src/store/_sql.py:15`), identifier whitelists (`_SORT_COLUMNS`, `src/store/reader/_browse.py:35`; the `_USER_COLUMNS` / `_SESSION_COLUMNS` constants in `src/appdb/`), and fixed clause fragments (`src/store/reader/_filters.py::build_filters`; the `col = ?` assignment lists in `src/appdb/users.py:360`, `src/appdb/api_keys.py:382`). FTS terms are escaped (`escape_fts_term`, `src/store/reader/_filters.py:103`) and re-quoted as a literal phrase by the caller (`src/store/reader/_ranked.py:130,206`).
- **Stored XSS via proxied files** (`src/search/document_routes/_proxy.py:64-79`) — `GET /api/documents/{id}/pdf` pins `Content-Type: application/pdf` (never forwards the upstream type); `/thumb` forwards only a 4-entry image allowlist (`image/jpeg`, `image/png`, `image/webp`, `image/gif`) and otherwise 502s. Both send `nosniff`. Do not "fix" these by passing the upstream type through.
- **LLM output** — non-string scalars from the model are coerced to `""` before they can enter the taxonomy (`src/classifier/result.py:51-63`); implausible dates (before 1900-01-01 or more than 366 days ahead) are dropped (`src/classifier/metadata.py:33-36`).

### Transport & headers

`SecurityHeadersMiddleware` (`src/search/security_headers.py:48-72`) stamps `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, HSTS (`max-age=31536000; includeSubDomains`) and a CSP (`default-src 'self'`, `script-src 'self' 'unsafe-inline'`, `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:`, `font-src 'self'`, `connect-src 'self'`, `frame-ancestors 'none'`, `base-uri 'self'`, `object-src 'none'`). It is **additive** — a header a handler already set is left alone, which is how the PDF/thumb proxy relaxes framing to `X-Frame-Options: SAMEORIGIN` + `frame-ancestors 'self'` for the in-app viewer. `'unsafe-inline'` exists for the single pre-paint theme script in `web/index.html:7`; `'unsafe-eval'` is deliberately withheld. `/openapi.json`, `/docs` and `/redoc` are disabled (`src/search/api.py:392-400`).

CSRF defence is the `SameSite=Strict` cookie — there is no CSRF token (`src/search/sessions.py:18`, `src/search/cookies.py:10`).

### Supply chain & runtime

| Gate | Command / fact | Source |
|------|----------------|--------|
| Static analysis | `bandit -r src/ -ll -f txt` (MEDIUM+) | `.github/workflows/ci.yml` (`security-scan`) |
| Python deps | `pip-audit` | `.github/workflows/ci.yml` (`dependency-audit`) |
| JS deps | `npm audit --omit=dev --audit-level=high` | `.github/workflows/ci.yml` (`frontend`) |
| Image build | gated on every check job, not just tests | `.github/workflows/ci.yml` (`docker` `needs:`) |
| Transitive pins | `overrides`: `handlebars`, `uuid`, `esbuild`, `js-yaml` | `web/package.json:16-21` |
| Runtime container | non-root `appuser`; wheels installed offline (`pip install --no-index --find-links=/app/wheels`), so the runtime has no PyPI access and no compiler (`build-essential` is builder-stage only) | `Dockerfile:102,124,138` |

## Procedures

1. **Rotate a leaked API key** — revoke it (`DELETE /api/api-keys/{id}`; soft delete sets `revoked_at`, keeping usage history) and mint a new one; the raw key is unrecoverable by design.
2. **Lock down the proxy** — set `SEARCH_FORWARDED_ALLOW_IPS` to the reverse-proxy IP or CIDR (uvicorn 0.47 accepts both) whenever the uvicorn port is reachable directly.
3. **Reveal a stored secret** (admin, audited) — `GET /api/settings?reveal=true`; the revealed *keys* are logged as `search.settings_revealed` with the actor's username, never the values (`src/search/settings_routes.py:180-188`).

## Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Forged client IP in `sessions.ip`, or a cookie missing `Secure` | `SEARCH_FORWARDED_ALLOW_IPS` defaults to `*` (`src/common/config/_settings.py:770`), so `X-Forwarded-For`/`-Proto` are trusted from any peer — safe only while the uvicorn port is proxy-only | Pin the setting to the proxy IP/CIDR |
| Lockout leniency in a multi-instance deployment | The login throttle, the result cache (`src/search/cache.py`), the core cache (`src/search/api.py:520-529`) and the setup token are **process-local** singletons; the architecture assumes one search-server process | Run one search server, or accept N× leniency |
| SPA breaks under CSP after adding a dependency | A new library uses `eval`/`new Function` (blocked) or a second inline `<script>` appears in `index.html` | Remove the eval-using dependency; keep exactly one inline script |
| In-app PDF viewer goes blank | The security middleware was changed to overwrite (rather than skip) headers a handler set | Keep it additive |
| A legitimately redacted or refusal-quoting document is error-tagged | The document-level content gate (`is_error_content`, `src/common/content_checks.py:16`, called from `src/ocr/worker.py:255` and `src/classifier/quality_gates.py:30`) has **no** length threshold, unlike the OCR provider's 200-char refusal-dominance rule (`src/ocr/provider.py:22`) | Known asymmetry — expect false positives on denial letters / redacted bodies |

## Related

- [ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [CONFIGURATION](CONFIGURATION.md) · [modules/search-api](modules/search-api.md)
- The law: `CODE_GUIDELINES.md` §10 (Security)
