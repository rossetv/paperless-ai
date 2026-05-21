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
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  StatusResponse,
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

  // 202 Accepted / 204 No Content have no body to parse.
  if (response.status === 202 || response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Typed endpoint functions
// ---------------------------------------------------------------------------

/**
 * POST /api/auth/login — exchange the API key for a signed session cookie.
 *
 * On success the server sets an `HttpOnly` session cookie; the SPA does not
 * store the key anywhere in JS-accessible memory.
 */
export async function login(body: LoginRequest): Promise<StatusResponse> {
  return request<StatusResponse>(`${BASE_URL}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
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
