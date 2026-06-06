/**
 * Search endpoint functions — run queries, fetch facets, stats, health, and
 * reconcile triggers.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  StatusResponse,
  RecentSearchesResponse,
} from '../types';
import { BASE_URL, request } from './core';

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

/**
 * Build the URL of the first-page thumbnail proxy for a document.
 *
 * `GET /api/documents/{id}/thumb` streams the document's first-page thumbnail
 * (proxied from Paperless-ngx by the search server). LibraryCard points an
 * `<img src>` at this URL; the session cookie is sent automatically because it
 * is a same-origin request — no `credentials` flag is needed (and a binary
 * stream must not be funnelled through the JSON `request` helper).
 */
export function documentThumbUrl(documentId: number): string {
  return `${BASE_URL}/api/documents/${documentId}/thumb`;
}
