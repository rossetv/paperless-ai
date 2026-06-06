/**
 * Index-operations endpoint functions — Wave 6.
 *
 * Daemon status, reconcile-activity history, failed documents, and the
 * rebuild trigger.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  RebuildResponse,
} from '../types';
import { BASE_URL, request } from './core';

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
 * typed confirmation — the client module itself adds no guard.
 */
export async function rebuildIndex(): Promise<RebuildResponse> {
  return request<RebuildResponse>(`${BASE_URL}/api/index/rebuild`, { method: 'POST' });
}
