/** User-management and API-key wire types. */

import type { User } from './auth';

/** Body for POST /api/users — create a user account. */
export interface CreateUserRequest {
  username: string;
  password: string;
  display_name: string | null;
  email: string | null;
  role: 'admin' | 'member' | 'readonly';
}

/**
 * Body for PATCH /api/users/{id} — edit a user; only the supplied fields change.
 *
 * A non-empty `password` resets the password. Fields are `field?: X | null` to
 * mirror the backend's `str | None = None`.
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
 * No `owner_id`: the backend always makes the caller the owner. Admins can view
 * and revoke other users' keys but cannot mint keys for them.
 */
export interface CreateApiKeyRequest {
  name: string;
  scopes: ApiScope[];
  /** ISO-8601 expiry, or null for a key that never expires. */
  expires_at: string | null;
}

/**
 * Body for PATCH /api/api-keys/{id} — edit a key; only the supplied fields change.
 *
 * Owner-only (403 otherwise). `expires_at: null` clears the expiry; omit it to
 * leave the expiry unchanged.
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
 * `secret` is the full `sk-pls-…` key, returned only here; the UI shows it once
 * for the user to copy, then discards it.
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
