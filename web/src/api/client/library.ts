/** Library and document endpoints: list, fetch, metadata patch, AI re-runs and deletion. */

import type {
  DocumentsQuery,
  DocumentsResponse,
  LibraryDocument,
  DocumentPatch,
} from '../types';
import { BASE_URL, request } from './core';

/**
 * Build the query string for GET /api/documents.
 *
 * Optional filters are sent only when non-nullish and non-empty; `tag_ids`
 * repeats once per id, the FastAPI list-query convention.
 */
function buildDocumentsQuery(q: DocumentsQuery): string {
  const params = new URLSearchParams();
  params.set('page', String(q.page));
  params.set('page_size', String(q.page_size));
  params.set('sort', q.sort);
  params.set('descending', String(q.descending));
  if (q.query != null && q.query.trim() !== '') {
    params.set('query', q.query.trim());
  }
  if (q.correspondent_id != null) {
    params.set('correspondent_id', String(q.correspondent_id));
  }
  if (q.document_type_id != null) {
    params.set('document_type_id', String(q.document_type_id));
  }
  if (q.date_from != null && q.date_from !== '') {
    params.set('date_from', q.date_from);
  }
  if (q.date_to != null && q.date_to !== '') {
    params.set('date_to', q.date_to);
  }
  for (const tagId of q.tag_ids) {
    params.append('tag_ids', String(tagId));
  }
  return params.toString();
}

/** GET /api/documents — the paginated, sortable, filterable library list. */
export async function getDocuments(
  query: DocumentsQuery,
): Promise<DocumentsResponse> {
  const qs = buildDocumentsQuery(query);
  return request<DocumentsResponse>(`${BASE_URL}/api/documents?${qs}`, {
    method: 'GET',
  });
}

/**
 * GET /api/documents/{id} — one document's metadata.
 *
 * Used when a shareable URL (`/document/:id`, `/library/document/:id`) opens the
 * preview with no cached library list to read from.
 */
export async function getDocument(documentId: number): Promise<LibraryDocument> {
  return request<LibraryDocument>(`${BASE_URL}/api/documents/${documentId}`, {
    method: 'GET',
  });
}

/**
 * PATCH /api/documents/{id} — partially update a document's metadata.
 *
 * A `null` value clears the field; an omitted key leaves it unchanged.
 */
export async function patchDocument(
  id: number,
  patch: DocumentPatch,
): Promise<LibraryDocument> {
  return request<LibraryDocument>(`${BASE_URL}/api/documents/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
}

/**
 * POST /api/documents/{id}/reclassify — queue AI re-classification.
 *
 * Resolves on 202; the job runs asynchronously. A readonly caller gets 403.
 */
export async function reclassifyDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}/reclassify`, { method: 'POST' });
}

/** POST /api/documents/{id}/retranscribe — queue AI re-transcription (OCR); resolves on 202. */
export async function retranscribeDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}/retranscribe`, { method: 'POST' });
}

/**
 * DELETE /api/documents/{id} — permanently delete a document in Paperless-ngx.
 *
 * Irreversible and admin-only (403 otherwise). Resolves on 204.
 */
export async function deleteDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}`, { method: 'DELETE' });
}
