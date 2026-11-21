/** Index-operations endpoints: daemon status, reconcile history, failed documents, rebuild. */

import type {
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  RebuildResponse,
} from '../types';
import { BASE_URL, request } from './core';

/** GET /api/index/status — daemon statuses and index health (polled by `useIndexStatus`). */
export async function getIndexStatus(): Promise<IndexStatusResponse> {
  return request<IndexStatusResponse>(`${BASE_URL}/api/index/status`, {
    method: 'GET',
  });
}

/** GET /api/index/activity — recent reconcile cycles (polled by `useIndexActivity`). */
export async function getIndexActivity(): Promise<IndexActivityResponse> {
  return request<IndexActivityResponse>(`${BASE_URL}/api/index/activity`, {
    method: 'GET',
  });
}

/** GET /api/index/failed — documents that failed OCR, classification or indexing. */
export async function getFailedDocuments(): Promise<IndexFailedResponse> {
  return request<IndexFailedResponse>(`${BASE_URL}/api/index/failed`, {
    method: 'GET',
  });
}

/**
 * POST /api/index/rebuild — destroy `index.db` and re-embed every document.
 *
 * Destructive and admin-only: 403 for a non-admin, 503 if the sentinel directory
 * is not writable. The typed confirmation lives in `RebuildIndexCard`; this adds no guard.
 */
export async function rebuildIndex(): Promise<RebuildResponse> {
  return request<RebuildResponse>(`${BASE_URL}/api/index/rebuild`, { method: 'POST' });
}
