/** Search, facets, stats, health, reconcile and document-asset URL endpoints. */

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

/** POST /api/reconcile — trigger an immediate reconciliation cycle; resolves on 202. */
export async function postReconcile(): Promise<void> {
  return request<void>(`${BASE_URL}/api/reconcile`, { method: 'POST' });
}

/** GET /api/recent-searches — the signed-in user's recent queries, newest first. */
export async function getRecentSearches(): Promise<RecentSearchesResponse> {
  return request<RecentSearchesResponse>(
    `${BASE_URL}/api/recent-searches`,
    { method: 'GET' },
  );
}

/**
 * URL of the PDF proxy (`GET /api/documents/{id}/pdf`), loaded by the preview `<iframe>`.
 *
 * A same-origin navigation sends the session cookie by itself, and a binary
 * stream must not go through the JSON `request` helper.
 */
export function documentPdfUrl(documentId: number): string {
  return `${BASE_URL}/api/documents/${documentId}/pdf`;
}

/** URL of the first-page thumbnail proxy (`GET /api/documents/{id}/thumb`) for an `<img>`. */
export function documentThumbUrl(documentId: number): string {
  return `${BASE_URL}/api/documents/${documentId}/thumb`;
}
