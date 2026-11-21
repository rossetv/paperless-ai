/** List and create endpoints for correspondents, document types and tags. */

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

/** POST /api/correspondents — create a correspondent in Paperless-ngx. */
export async function createCorrespondent(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/correspondents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

/** POST /api/document-types — create a document type in Paperless-ngx. */
export async function createDocumentType(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/document-types`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

/** POST /api/tags — create a tag in Paperless-ngx. */
export async function createTag(name: string): Promise<TaxonomyItem> {
  return request<TaxonomyItem>(`${BASE_URL}/api/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}
