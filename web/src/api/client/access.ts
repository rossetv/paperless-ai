/**
 * User-management and API-key endpoint functions — Wave 3 (Access Control).
 *
 * Admin-only on the server. The frontend still calls them — a 403 surfaces
 * as `ApiError` and is handled by the route guard, not hidden here.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  CreateUserRequest,
  UpdateUserRequest,
  UsersResponse,
  UserResponse,
  CreateApiKeyRequest,
  UpdateApiKeyRequest,
  ApiKeysResponse,
  CreateApiKeyResponse,
  ApiKeyEnvelope,
} from '../types';
import { BASE_URL, request } from './core';

// ---------------------------------------------------------------------------
// User-management endpoints
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
// API-key endpoints
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
