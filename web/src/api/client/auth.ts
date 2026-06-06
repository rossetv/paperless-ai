/**
 * Auth and setup endpoint functions.
 *
 * Covers first-run setup, session login/logout, the `me` probe, and the
 * public stats call used on the login splash.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  LoginRequest,
  LoginResponse,
  MeResponse,
  SetupRequest,
  SetupResponse,
  SetupStatus,
  PublicStats,
} from '../types';
import { BASE_URL, request } from './core';

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
