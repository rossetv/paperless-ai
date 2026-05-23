/**
 * Typed fetch wrapper — the single point of backend contact for the React SPA.
 *
 * Security invariant (spec §7.3, §9.2):
 *   - Every request sends `credentials: 'include'` so the signed `HttpOnly`
 *     session cookie is attached automatically by the browser.
 *   - The API key is NEVER stored in or shipped with the frontend bundle.
 *     Authentication is done via the login handshake → cookie; the JS bundle
 *     never sees the raw `SEARCH_API_KEY`.
 *
 * Error model:
 *   - `Unauthenticated` — thrown on any 401 response; the app detects this
 *     class to route the user to the login screen.
 *   - `ApiError`        — thrown on any other non-2xx response.
 *   - 2xx              — resolved to the parsed JSON body (typed).
 *
 * Allowed deps: types.ts only (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  LoginRequest,
  LoginResponse,
  MeResponse,
  SetupRequest,
  SetupResponse,
  SetupStatus,
  PublicStats,
  CreateUserRequest,
  UpdateUserRequest,
  UsersResponse,
  UserResponse,
  CreateApiKeyRequest,
  UpdateApiKeyRequest,
  ApiKeysResponse,
  CreateApiKeyResponse,
  ApiKeyEnvelope,
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  StatusResponse,
  RecentSearchesResponse,
  SettingsResponse,
  UpdateSettingsRequest,
  TestConnectionRequest,
  TestConnectionResponse,
  DocumentsQuery,
  DocumentsResponse,
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  RebuildResponse,
} from './types';

// ---------------------------------------------------------------------------
// Base URL — configurable via import.meta.env for local dev; same-origin in prod
// ---------------------------------------------------------------------------

/** The base URL for all API calls. Same-origin in production; proxied in dev. */
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

// ---------------------------------------------------------------------------
// Error types
// ---------------------------------------------------------------------------

/**
 * Thrown when the server returns a 401 Unauthorised response.
 *
 * The app detects `instanceof Unauthenticated` to redirect to the login screen.
 * This is deliberately NOT a subclass of `ApiError` so the two cases are
 * structurally distinct at the catch site.
 */
export class Unauthenticated extends Error {
  readonly status = 401 as const;

  constructor(message = 'Unauthenticated — please log in') {
    super(message);
    this.name = 'Unauthenticated';
    // Restore the prototype chain (required when transpiling to ES5).
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

/**
 * Thrown when the server returns a non-2xx, non-401 response.
 *
 * Carries the HTTP status code for the caller to inspect.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message = `API error ${status}`) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

// ---------------------------------------------------------------------------
// Internal fetch helper
// ---------------------------------------------------------------------------

/**
 * Core fetch wrapper: attaches `credentials: 'include'`, normalises errors,
 * and returns the parsed JSON body typed as `T`.
 *
 * The `credentials: 'include'` flag ensures the signed `HttpOnly` session
 * cookie is sent with every cross-origin same-site request. Because the
 * cookie is `HttpOnly` the JS bundle cannot read or forward the raw key —
 * the browser is the only entity that sees it.
 *
 * A 202/204 response carries no body — `request` resolves to `undefined`
 * rather than attempting to parse one. An endpoint that returns no content
 * is typed `request<void>`.
 *
 * Additionally, a body-presence check guards against future endpoints that
 * return 200 with an empty body (e.g. a 304-equivalent or a no-content 200):
 * reading an empty body as JSON would throw a `SyntaxError`. The guard reads
 * the text first and skips JSON parsing when the body is empty.
 */
async function request<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: 'include',
  });

  if (!response.ok) {
    if (response.status === 401) {
      throw new Unauthenticated();
    }
    throw new ApiError(response.status);
  }

  // 202 Accepted / 204 No Content explicitly carry no body.
  if (response.status === 202 || response.status === 204) {
    return undefined as T;
  }

  // Guard against an empty body on any other 2xx — a `content-length: 0`
  // header or an actually-empty body both indicate no JSON to parse.
  const contentLength = response.headers.get('content-length');
  if (contentLength === '0') {
    return undefined as T;
  }

  const text = await response.text();
  if (text.trim().length === 0) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}

// ---------------------------------------------------------------------------
// Typed endpoint functions
// ---------------------------------------------------------------------------

/**
 * GET /api/setup/status — whether first-run setup is still needed.
 *
 * Public (no auth). `needed` is true while the `users` table is empty.
 */
export async function setupStatus(): Promise<SetupStatus> {
  return request<SetupStatus>(`${BASE_URL}/api/setup/status`, { method: 'GET' });
}

/**
 * POST /api/setup — create the first admin account.
 *
 * Authorised by the setup token printed to the container logs. Throws
 * `ApiError` with status 403 (bad token) or 409 (already set up).
 */
export async function setup(body: SetupRequest): Promise<SetupResponse> {
  return request<SetupResponse>(`${BASE_URL}/api/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/auth/login — sign in with username + password.
 *
 * On success the server sets an `HttpOnly` `search_session` cookie and
 * returns the user. Throws `Unauthenticated` on 401 (invalid credentials)
 * and `ApiError` on 403 (suspended account).
 */
export async function login(body: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/auth/logout — destroy the current server-side session.
 *
 * Resolves on 204 No Content. The session cookie is cleared server-side.
 */
export async function logout(): Promise<void> {
  return request<void>(`${BASE_URL}/api/auth/logout`, { method: 'POST' });
}

/**
 * GET /api/auth/me — the current authenticated user.
 *
 * Throws `Unauthenticated` on 401; the SPA treats that as "not signed in".
 */
export async function me(): Promise<MeResponse> {
  return request<MeResponse>(`${BASE_URL}/api/auth/me`, { method: 'GET' });
}

/**
 * GET /api/stats/public — minimal splash counts for the login screen.
 *
 * Public (no auth). Used only by the login splash; callers must degrade
 * gracefully if it fails.
 */
export async function publicStats(): Promise<PublicStats> {
  return request<PublicStats>(`${BASE_URL}/api/stats/public`, { method: 'GET' });
}

/** POST /api/search — run the agentic search pipeline. */
export async function search(body: SearchRequest): Promise<SearchResponse> {
  return request<SearchResponse>(`${BASE_URL}/api/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/** GET /api/facets — taxonomy facets for the filter panel. */
export async function getFacets(): Promise<FacetsResponse> {
  return request<FacetsResponse>(`${BASE_URL}/api/facets`, { method: 'GET' });
}

/** GET /api/stats — index statistics. */
export async function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>(`${BASE_URL}/api/stats`, { method: 'GET' });
}

/** GET /api/healthz — liveness check (unprotected). */
export async function getHealthz(): Promise<StatusResponse> {
  return request<StatusResponse>(`${BASE_URL}/api/healthz`, { method: 'GET' });
}

/**
 * POST /api/reconcile — trigger an immediate reconciliation cycle.
 *
 * Resolves on 202 Accepted; throws `Unauthenticated` on 401 and `ApiError`
 * on any other non-2xx. Routes through the shared `request` wrapper, which
 * skips body parsing for the empty 202 response.
 */
export async function postReconcile(): Promise<void> {
  return request<void>(`${BASE_URL}/api/reconcile`, { method: 'POST' });
}

/**
 * GET /api/recent-searches — the signed-in user's recent query history.
 *
 * Newest entry first. Requires a session; throws `Unauthenticated` on 401.
 * The idle search screen calls this and degrades gracefully if it fails.
 */
export async function getRecentSearches(): Promise<RecentSearchesResponse> {
  return request<RecentSearchesResponse>(
    `${BASE_URL}/api/recent-searches`,
    { method: 'GET' },
  );
}

/**
 * Build the URL of the in-app PDF proxy for a document.
 *
 * `GET /api/documents/{id}/pdf` streams the original PDF (proxied from
 * Paperless-ngx by the Wave 2 backend). The document-preview viewer points an
 * `<iframe src>` at this URL; the browser's built-in PDF viewer renders it.
 * The session cookie is sent automatically with the iframe request because it
 * is a same-origin navigation — no `credentials` flag is needed (and a binary
 * stream must not be funnelled through the JSON `request` helper).
 */
export function documentPdfUrl(documentId: number): string {
  return `${BASE_URL}/api/documents/${documentId}/pdf`;
}

// ---------------------------------------------------------------------------
// User-management endpoints (Wave 3 — Access Control)
//
// Admin-only on the server. The frontend still calls them — a 403 surfaces
// as `ApiError` and is handled by the route guard, not hidden here.
// ---------------------------------------------------------------------------

/** GET /api/users — list every user account. */
export async function getUsers(): Promise<UsersResponse> {
  return request<UsersResponse>(`${BASE_URL}/api/users`, { method: 'GET' });
}

/** POST /api/users — create a user account. */
export async function createUser(body: CreateUserRequest): Promise<UserResponse> {
  return request<UserResponse>(`${BASE_URL}/api/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * PATCH /api/users/{id} — edit a user.
 *
 * Only the fields present in `body` are changed. The server enforces the
 * last-admin and self-modification guards; a violation surfaces as `ApiError`.
 */
export async function updateUser(
  id: number,
  body: UpdateUserRequest,
): Promise<UserResponse> {
  return request<UserResponse>(`${BASE_URL}/api/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * DELETE /api/users/{id} — delete a user.
 *
 * Resolves on 204. The server forbids deleting the last admin or oneself;
 * either surfaces as `ApiError`.
 */
export async function deleteUser(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/users/${id}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// API-key endpoints (Wave 3 — Access Control)
// ---------------------------------------------------------------------------

/** GET /api/api-keys — list the API keys visible to the caller. */
export async function getApiKeys(): Promise<ApiKeysResponse> {
  return request<ApiKeysResponse>(`${BASE_URL}/api/api-keys`, { method: 'GET' });
}

/**
 * POST /api/api-keys — mint a new API key.
 *
 * The response carries the full one-time `secret`. The caller MUST show it
 * once and never persist it — only the prefix is retrievable afterwards.
 */
export async function createApiKey(
  body: CreateApiKeyRequest,
): Promise<CreateApiKeyResponse> {
  return request<CreateApiKeyResponse>(`${BASE_URL}/api/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * PATCH /api/api-keys/{id} — edit an API key.
 *
 * Only the fields present in `body` are changed. Editing is owner-only on
 * the server; a non-owner caller gets a 403 surfaced as `ApiError`. The
 * response carries the updated key — never a secret.
 */
export async function updateApiKey(
  id: number,
  body: UpdateApiKeyRequest,
): Promise<ApiKeyEnvelope> {
  return request<ApiKeyEnvelope>(`${BASE_URL}/api/api-keys/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * DELETE /api/api-keys/{id} — revoke or delete an API key.
 *
 * Resolves on 204. The server revokes an active key and deletes an already
 * expired one; the caller need not distinguish.
 */
export async function deleteApiKey(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/api-keys/${id}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Settings endpoints (Wave 4 — Settings)
//
// Admin-only on the server. A non-admin caller gets a 403, surfaced as
// `ApiError`; the route guard prevents a non-admin reaching the screen at all.
// ---------------------------------------------------------------------------

/** GET /api/settings — the current configuration values plus their metadata. */
export async function getSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>(`${BASE_URL}/api/settings`, { method: 'GET' });
}

/**
 * PUT /api/settings — persist changed configuration values.
 *
 * The body carries ONLY the keys the user changed. The server validates the
 * whole resulting config; a validation failure surfaces as `ApiError` (400).
 * The response is the re-read state — the source of truth after the save.
 */
export async function updateSettings(
  body: UpdateSettingsRequest,
): Promise<SettingsResponse> {
  return request<SettingsResponse>(`${BASE_URL}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/settings/test-connection — probe the Paperless connection.
 *
 * Takes the LIVE form values (not the saved config) so the user can test a
 * URL/token pair before committing it. A reachable-but-rejected probe
 * resolves to `{ ok: false, detail }`; a network failure throws `ApiError`.
 */
export async function testConnection(
  body: TestConnectionRequest,
): Promise<TestConnectionResponse> {
  return request<TestConnectionResponse>(
    `${BASE_URL}/api/settings/test-connection`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
}

// ---------------------------------------------------------------------------
// Library — GET /api/documents (Wave 5)
// ---------------------------------------------------------------------------

/**
 * Build the `?…` query string for GET /api/documents.
 *
 * `page`, `page_size`, `sort` and `descending` are always present. Optional
 * filters are appended only when non-nullish and (for strings) non-empty.
 * `tag_ids` becomes one repeated `tag_ids=` parameter per id, matching the
 * FastAPI list-query convention the backend half declared.
 */
function buildDocumentsQuery(q: DocumentsQuery): string {
  const params = new URLSearchParams();
  params.set('page', String(q.page));
  params.set('page_size', String(q.page_size));
  params.set('sort', q.sort);
  params.set('descending', String(q.descending));
  if (q.query != null && q.query.trim() !== '') {
    params.set('query', q.query.trim());
  }
  if (q.correspondent_id != null) {
    params.set('correspondent_id', String(q.correspondent_id));
  }
  if (q.document_type_id != null) {
    params.set('document_type_id', String(q.document_type_id));
  }
  if (q.date_from != null && q.date_from !== '') {
    params.set('date_from', q.date_from);
  }
  if (q.date_to != null && q.date_to !== '') {
    params.set('date_to', q.date_to);
  }
  for (const tagId of q.tag_ids) {
    params.append('tag_ids', String(tagId));
  }
  return params.toString();
}

/**
 * GET /api/documents — the paginated, sortable, filterable library list.
 *
 * Throws `Unauthenticated` on 401 and `ApiError` on any other non-2xx, via
 * the shared `request` wrapper.
 */
export async function getDocuments(
  query: DocumentsQuery,
): Promise<DocumentsResponse> {
  const qs = buildDocumentsQuery(query);
  return request<DocumentsResponse>(`${BASE_URL}/api/documents?${qs}`, {
    method: 'GET',
  });
}

// ---------------------------------------------------------------------------
// Index-operations endpoints (Wave 6 — Index)
// ---------------------------------------------------------------------------

/**
 * GET /api/index/status — daemon statuses and index health.
 *
 * Drives the Index dashboard hero, the stat-tile row and the daemon cards.
 * Polled on an interval by `useIndexStatus`.
 */
export async function getIndexStatus(): Promise<IndexStatusResponse> {
  return request<IndexStatusResponse>(`${BASE_URL}/api/index/status`, {
    method: 'GET',
  });
}

/**
 * GET /api/index/activity — the recent reconcile-cycle history.
 *
 * Drives the "Recent activity" panel. Polled on an interval by
 * `useIndexActivity`.
 */
export async function getIndexActivity(): Promise<IndexActivityResponse> {
  return request<IndexActivityResponse>(`${BASE_URL}/api/index/activity`, {
    method: 'GET',
  });
}

/**
 * GET /api/index/failed — documents that failed OCR / classification /
 * indexing.
 *
 * Drives the "Failed documents" panel.
 */
export async function getFailedDocuments(): Promise<IndexFailedResponse> {
  return request<IndexFailedResponse>(`${BASE_URL}/api/index/failed`, {
    method: 'GET',
  });
}

/**
 * POST /api/index/rebuild — destroy `index.db` and re-embed every document.
 *
 * DESTRUCTIVE and admin-only. Resolves on 200 OK with a `RebuildResponse`
 * body; throws `Unauthenticated` on 401 and `ApiError` on any other non-2xx
 * (notably 403 for a non-admin caller, 503 if the sentinel directory is not
 * writable). The caller (`RebuildIndexCard`) gates this behind an explicit
 * typed confirmation — `client.ts` itself adds no guard.
 */
export async function rebuildIndex(): Promise<RebuildResponse> {
  return request<RebuildResponse>(`${BASE_URL}/api/index/rebuild`, { method: 'POST' });
}
