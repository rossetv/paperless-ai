/**
 * User-management and API-key wire types — Wave 3 Access Control.
 *
 * Covers the users CRUD endpoints and the API-key mint/revoke lifecycle.
 * The `User` shape is imported from auth.ts as the shared base type.
 *
 * Allowed deps: auth.ts (peer module — CODE_GUIDELINES §12.3).
 */

import type { User } from './auth';

// ---------------------------------------------------------------------------
// User-management types (Wave 3 — Access Control)
//
// These consume the Wave 1 users CRUD endpoints. `User` (auth.ts) is the
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
 *
 * `role`, `status`, and `password` mirror the Python `wire.py` declaration of
 * `str | None = None` — each is therefore `field?: X | null` per the contract
 * guideline in types.ts.
 */
export interface UpdateUserRequest {
  display_name?: string | null;
  email?: string | null;
  role?: 'admin' | 'member' | 'readonly' | null;
  status?: 'active' | 'suspended' | null;
  password?: string | null;
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
