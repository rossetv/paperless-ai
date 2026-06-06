/**
 * Library and document-editing endpoint functions — Wave 5 / Wave 8/9.
 *
 * Covers the paginated document list, individual document fetch, metadata
 * patch, AI re-classification / re-transcription, and document deletion.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  DocumentsQuery,
  DocumentsResponse,
  LibraryDocument,
  DocumentPatch,
} from '../types';
import { BASE_URL, request } from './core';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Build the `?…` query string for GET /api/documents.
 *
 * `page`, `page_size`, `sort` and `descending` are always present. Optional
 * filters are appended only when non-nullish and (for strings) non-empty.
 * `tag_ids` becomes one repeated `tag_ids=` parameter per id, matching the
 * FastAPI list-query convention the backend declared.
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

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/**
 * GET /api/documents — the paginated, sortable, filterable library list.
 *
 * Throws `Unauthenticated` on 401 and `ApiError` on any other non-2xx, via
 * the shared `request` wrapper.
 */
export async function getDocuments(
  query: DocumentsQuery,
): Promise<DocumentsResponse> {
  const qs = buildDocumentsQuery(query);
  return request<DocumentsResponse>(`${BASE_URL}/api/documents?${qs}`, {
    method: 'GET',
  });
}

/**
 * GET /api/documents/{id} — fetch one document's metadata.
 *
 * Used by the route components that mount the document preview from a
 * shareable URL (`/document/:id`, `/library/document/:id`) when there is
 * no cached library list to read from. Returns the same `LibraryDocument`
 * shape as items in the library list response.
 *
 * Throws `Unauthenticated` on 401 and `ApiError` on any other non-2xx.
 */
export async function getDocument(documentId: number): Promise<LibraryDocument> {
  return request<LibraryDocument>(`${BASE_URL}/api/documents/${documentId}`, {
    method: 'GET',
  });
}

/**
 * PATCH /api/documents/{id} — partially update a document's metadata.
 *
 * Only the fields present in `patch` are forwarded to Paperless-ngx. A `null`
 * value clears the field; omitting the key leaves it unchanged. Returns the
 * updated `LibraryDocument` shape.
 *
 * Throws `Unauthenticated` on 401, `ApiError` on any other non-2xx.
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
 * POST /api/documents/{id}/reclassify — trigger AI re-classification for a document.
 *
 * Resolves on 202 Accepted. The backend queues the job; actual classification
 * happens asynchronously. Throws `Unauthenticated` on 401 and `ApiError` on
 * any other non-2xx (notably 403 for a readonly caller).
 */
export async function reclassifyDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}/reclassify`, { method: 'POST' });
}

/**
 * POST /api/documents/{id}/retranscribe — trigger AI re-transcription (OCR) for a document.
 *
 * Resolves on 202 Accepted. The backend queues the job; actual transcription
 * happens asynchronously. Throws `Unauthenticated` on 401 and `ApiError` on
 * any other non-2xx.
 */
export async function retranscribeDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}/retranscribe`, { method: 'POST' });
}

/**
 * DELETE /api/documents/{id} — permanently delete a document in Paperless-ngx.
 *
 * Resolves on 204 No Content. This operation is irreversible — the document is
 * removed from Paperless-ngx and cannot be restored via the search server.
 * Admin-only; a non-admin caller receives 403 surfaced as `ApiError`.
 */
export async function deleteDocument(id: number): Promise<void> {
  return request<void>(`${BASE_URL}/api/documents/${id}`, { method: 'DELETE' });
}
