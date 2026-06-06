/**
 * Taxonomy endpoint functions — correspondents, document types, and tags.
 *
 * Covers GET (list all) and POST (create) for each of the three taxonomy
 * types. All three share the same `TaxonomyItem` response shape.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type { TaxonomyItem } from '../types';
import { BASE_URL, request } from './core';

/** GET /api/correspondents — all correspondents available in Paperless-ngx. */
export async function getCorrespondents(): Promise<TaxonomyItem[]> {
  return request<TaxonomyItem[]>(`${BASE_URL}/api/correspondents`, { method: 'GET' });
}

/** GET /api/document-types — all document types available in Paperless-ngx. */
export async function getDocumentTypes(): Promise<TaxonomyItem[]> {
  return request<TaxonomyItem[]>(`${BASE_URL}/api/document-types`, { method: 'GET' });
}

/** GET /api/tags — all tags available in Paperless-ngx. */
export async function getTags(): Promise<TaxonomyItem[]> {
  return request<TaxonomyItem[]>(`${BASE_URL}/api/tags`, { method: 'GET' });
}

/**
 * POST /api/correspondents — create a new correspondent in Paperless-ngx.
 *
 * Returns the newly created correspondent (with its assigned id and zero
 * `document_count`).
 */
export async function createCorrespondent(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/correspondents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

/**
 * POST /api/document-types — create a new document type in Paperless-ngx.
 *
 * Returns the newly created document type (with its assigned id and zero
 * `document_count`).
 */
export async function createDocumentType(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/document-types`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

/**
 * POST /api/tags — create a new tag in Paperless-ngx.
 *
 * Returns the newly created tag (with its assigned id and zero
 * `document_count`).
 */
export async function createTag(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}
