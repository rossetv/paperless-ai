/**
 * Wire types mirroring the Python Pydantic models in `src/search/wire.py`.
 *
 * These types are the cross-language contract between the React SPA and the
 * FastAPI server. Field names and optionality MUST mirror `wire.py` exactly —
 * a divergence is a bug, not a style choice (CODE_GUIDELINES §12.6).
 *
 * Python `X | None` with no default → TypeScript `field: X | null`.
 * Python `X | None = None`          → TypeScript `field?: X | null`.
 * Python `list[X] = Field(default_factory=list)` → TypeScript `field: X[]`.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

// ---------------------------------------------------------------------------
// Account & auth types (Wave 1 — Accounts)
// ---------------------------------------------------------------------------

/** A user account, as returned by the server. Mirrors the Wave 1 contract. */
export interface User {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  role: 'admin' | 'member' | 'readonly';
  status: 'active' | 'suspended';
  created_at: string;
  last_login_at: string | null;
}

/** Response body for GET /api/setup/status. */
export interface SetupStatus {
  /** True when no users exist yet — the first-run setup screen must show. */
  needed: boolean;
}

/** Body for POST /api/setup — create the first admin account. */
export interface SetupRequest {
  /** The setup token printed to the container logs. */
  token: string;
  /** Desired admin username. */
  username: string;
  /** Desired admin password. */
  password: string;
}

/** Response body for POST /api/setup — the freshly created admin. */
export interface SetupResponse {
  user: User;
}

/** Body for POST /api/auth/login. */
export interface LoginRequest {
  username: string;
  password: string;
  /** "Keep me signed in for 7 days" — extends the session TTL. */
  remember: boolean;
}

/** Response body for POST /api/auth/login. */
export interface LoginResponse {
  user: User;
}

/** Response body for GET /api/auth/me — the current user. */
export interface MeResponse {
  user: User;
}

/** Response body for GET /api/stats/public — splash counts only. */
export interface PublicStats {
  document_count: number;
  chunk_count: number;
}

// ---------------------------------------------------------------------------
// User-management types (Wave 3 — Access Control)
//
// These consume the Wave 1 users CRUD endpoints. `User` (above) is the
// returned shape; the request bodies below mirror the server contract.
// ---------------------------------------------------------------------------

/** Body for POST /api/users — create a user account. */
export interface CreateUserRequest {
  username: string;
  password: string;
  display_name: string | null;
  email: string | null;
  role: 'admin' | 'member' | 'readonly';
}

/**
 * Body for PATCH /api/users/{id} — edit a user.
 *
 * Every field is optional: only the supplied fields are changed. A non-empty
 * `password` resets the password; omit it to keep the current one.
 */
export interface UpdateUserRequest {
  display_name?: string | null;
  email?: string | null;
  role?: 'admin' | 'member' | 'readonly';
  status?: 'active' | 'suspended';
  password?: string;
}

/** Response body for GET /api/users — all user accounts. */
export interface UsersResponse {
  users: User[];
}

/** Response body for POST /api/users and PATCH /api/users/{id}. */
export interface UserResponse {
  user: User;
}

// ---------------------------------------------------------------------------
// API-key types (Wave 3 — Access Control)
// ---------------------------------------------------------------------------

/** The scopes an API key may carry. */
export type ApiScope = 'api' | 'mcp' | 'admin';

/**
 * An API key, as returned by the server.
 *
 * The full secret is NEVER in this shape — only `key_prefix` (the leading
 * identifying segment). `expires_at: null` means the key never expires;
 * `revoked_at` is set once a key is revoked.
 */
export interface ApiKey {
  id: number;
  name: string;
  key_prefix: string;
  scopes: ApiScope[];
  owner_id: number;
  owner_name: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  request_count: number;
}

/**
 * Body for POST /api/api-keys — mint a new key.
 *
 * There is no `owner_id`: an API key is always owned by the caller who
 * creates it. The backend hard-wires `owner_user_id = caller.id`, so an
 * `owner_id` here would be silently ignored. Admins can view and revoke
 * other users' keys but cannot mint keys on their behalf.
 */
export interface CreateApiKeyRequest {
  name: string;
  scopes: ApiScope[];
  /** ISO-8601 expiry, or null for a key that never expires. */
  expires_at: string | null;
}

/**
 * Body for PATCH /api/api-keys/{id} — edit a key.
 *
 * Every field is optional: only the supplied fields change. Editing is
 * **owner-only** — the backend returns 403 unless the caller owns the key.
 * `expires_at: null` clears the expiry (the key never expires); omit the
 * field to leave the expiry unchanged.
 */
export interface UpdateApiKeyRequest {
  name?: string;
  scopes?: ApiScope[];
  expires_at?: string | null;
}

/** Response body for GET /api/api-keys — all keys visible to the caller. */
export interface ApiKeysResponse {
  keys: ApiKey[];
}

/**
 * Response body for POST /api/api-keys.
 *
 * `api_key` is the persisted key metadata. `secret` is the full `sk-pls-…`
 * key — returned ONCE, at creation, and never again. The UI shows the secret
 * once for the user to copy, then discards it.
 */
export interface CreateApiKeyResponse {
  api_key: ApiKey;
  secret: string;
}

/**
 * Response body for PATCH /api/api-keys/{id} — the updated key.
 *
 * Carries no `secret`: editing a key never re-reveals it.
 */
export interface ApiKeyEnvelope {
  api_key: ApiKey;
}

// ---------------------------------------------------------------------------
// Search request types
// ---------------------------------------------------------------------------

/** Optional filters supplied in a search request (spec §7.1). */
export interface FilterRequest {
  date_from?: string | null;
  date_to?: string | null;
  correspondent_id?: number | null;
  document_type_id?: number | null;
  tag_ids: number[];
}

/** Body for POST /api/search. */
export interface SearchRequest {
  query: string;
  filters?: FilterRequest | null;
}

// ---------------------------------------------------------------------------
// Response sub-types
// ---------------------------------------------------------------------------

/** A single taxonomy entry as returned to the browser. */
export interface TaxonomyEntry {
  kind: string;
  id: number;
  name: string;
}

/** One ranked source document in the search response. */
export interface SourceDocument {
  document_id: number;
  title: string | null;
  correspondent: string | null;
  document_type: string | null;
  created: string | null;
  snippet: string;
  paperless_url: string;
  score: number;
}

/** The query plan for UI transparency (spec §7.1). */
export interface QueryPlan {
  semantic_queries: string[];
  keyword_terms: string[];
  sub_questions: string[];
}

/** Execution statistics for UI transparency and debugging. */
export interface SearchStats {
  llm_calls: number;
  latency_ms: number;
  refined: boolean;
}

// ---------------------------------------------------------------------------
// Top-level response types
// ---------------------------------------------------------------------------

/** Response body for POST /api/search. */
export interface SearchResponse {
  answer: string;
  sources: SourceDocument[];
  plan: QueryPlan;
  stats: SearchStats;
}

/** Response body for GET /api/facets. */
export interface FacetsResponse {
  correspondents: TaxonomyEntry[];
  document_types: TaxonomyEntry[];
  tags: TaxonomyEntry[];
  earliest: string | null;
  latest: string | null;
}

/** Response body for GET /api/stats. */
export interface StatsResponse {
  document_count: number;
  chunk_count: number;
  last_reconcile_at: string | null;
  embedding_model: string | null;
}

/** Response body for GET /api/healthz. */
export interface StatusResponse {
  status: string;
}

// ---------------------------------------------------------------------------
// Recent searches (Wave 2 — Search redesign)
// ---------------------------------------------------------------------------

/**
 * One entry in the signed-in user's recent-search history.
 *
 * Mirrors `RecentSearchEntry` in `src/search/wire.py`: a row of the
 * `recent_searches` table added by the Wave 2 backend (`app.db` migration
 * v2). `created_at` is an ISO-8601 UTC timestamp.
 */
export interface RecentSearch {
  /** The raw query text the user searched for. */
  query: string;
  /** ISO-8601 UTC timestamp of when the search ran. */
  created_at: string;
}

/** Response body for GET /api/recent-searches — newest entry first. */
export interface RecentSearchesResponse {
  searches: RecentSearch[];
}

// ---------------------------------------------------------------------------
// Settings / configuration types (Wave 4 — Settings)
//
// The Settings screen edits the 51 config keys that the backend has moved
// from environment variables into the `config` table on app.db. The keys are
// the field names of the server's `Settings` dataclass.
// ---------------------------------------------------------------------------

/**
 * One configuration key as the server returns it.
 *
 * `value` is the effective value as a STRING, or `null` when the key is on
 * its coded default. For a secret key it is a fixed mask string, never the
 * real secret. The field model in `features/settings` parses `value` to the
 * key's real type (number / boolean / CSV list).
 */
export interface SettingItem {
  /** The canonical config-key name (a `Settings`-dataclass field name). */
  key: string;
  /** The effective value as a string, or null when on the coded default. */
  value: string | null;
  /** Where the value came from: 'database' | 'environment' | 'default'. */
  source: string;
  /** True for secret keys — `value` is masked; the UI offers a reveal. */
  is_secret: boolean;
  /** True when changing this key requires a full document re-index. */
  requires_reindex: boolean;
}

/**
 * Response body for GET /api/settings and PUT /api/settings.
 *
 * A flat list, one item per config key. PUT returns this same shape — the
 * re-read state — so the screen refreshes itself from the one response.
 */
export interface SettingsResponse {
  settings: SettingItem[];
}

/**
 * Body for PUT /api/settings.
 *
 * `changes` carries only the keys the user changed, each as a STRING — the
 * config table is string-only, so the frontend serialises numbers, booleans
 * and CSV lists to strings before posting. An unchanged masked secret is
 * omitted — the server keeps the stored value when a key is absent.
 */
export interface UpdateSettingsRequest {
  changes: Record<string, string>;
}

/** Body for POST /api/settings/test-connection — the current form values. */
export interface TestConnectionRequest {
  /** The Paperless server URL to probe — the live form value, not the saved one. */
  paperless_url: string;
  /**
   * The Paperless API token to probe with — the live form value. An empty
   * string means "probe with the stored token" (the masked-token path: the
   * user has not replaced the secret).
   */
  paperless_token: string;
}

/**
 * Response body for POST /api/settings/test-connection.
 *
 * `ok` is true when the round-trip succeeded; `document_count` is then the
 * count Paperless reported. `ok` is false (with `document_count: 0` and an
 * explanatory `detail`) when the server was reached but the token or URL was
 * rejected, or the host was unreachable.
 */
export interface TestConnectionResponse {
  ok: boolean;
  document_count: number;
  detail: string;
}
