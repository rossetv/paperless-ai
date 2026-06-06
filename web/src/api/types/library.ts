/**
 * Library wire types — GET /api/documents (Wave 5).
 *
 * The paginated, sortable, filterable document list and individual document
 * metadata. Also covers the document-editing patch shape and taxonomy items
 * used in the document-edit panel (Wave 8/9).
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

// ---------------------------------------------------------------------------
// Library — GET /api/documents (Wave 5)
// ---------------------------------------------------------------------------

/**
 * Sort field for the library document list.
 *
 * Mirrors the backend ``Literal["created", "title", "added"]`` on
 * ``GET /api/documents``.  ``added`` is the date the document was indexed
 * (``indexed_at``); ``created`` is the document's own creation date.
 */
export type DocumentSortField = 'created' | 'title' | 'added';

/**
 * Query parameters for GET /api/documents.
 *
 * `page` is 1-based. All filter fields are optional and omitted from the
 * query string when nullish. `tag_ids` is serialised as one repeated
 * `tag_ids=` parameter per id.
 *
 * `descending` maps directly to the backend's boolean query parameter —
 * `true` for newest/largest first, `false` for oldest/smallest first.
 */
export interface DocumentsQuery {
  /** 1-based page number. */
  page: number;
  /** Rows per page. */
  page_size: number;
  /** Field to order by. */
  sort: DocumentSortField;
  /** True for descending order (newest/largest first); false for ascending. */
  descending: boolean;
  /** Free-text filter over title / correspondent / type. */
  query?: string | null;
  /** Restrict to a single correspondent by id. */
  correspondent_id?: number | null;
  /** Restrict to a single document type by id. */
  document_type_id?: number | null;
  /** Restrict to documents carrying every listed tag id. */
  tag_ids: number[];
  /** Inclusive lower bound on the document `created` date (ISO-8601). */
  date_from?: string | null;
  /** Inclusive upper bound on the document `created` date (ISO-8601). */
  date_to?: string | null;
}

/** One document row in the library list response. */
export interface LibraryDocument {
  /** Paperless document id. */
  id: number;
  /** Document title; null when Paperless has none. */
  title: string | null;
  /** Correspondent name; null when unset. */
  correspondent: string | null;
  /** Document-type name; null when unset. */
  document_type: string | null;
  /** Creation date as ISO-8601; null when unknown. */
  created: string | null;
  /** Tag names attached to the document. */
  tags: string[];
  /** Number of pages in the document; null when the page count is unknown. */
  page_count: number | null;
  /** Deep-link URL into Paperless-ngx for this document. */
  paperless_url: string;
}

/** Response body for GET /api/documents. */
export interface DocumentsResponse {
  /** The page of documents. */
  documents: LibraryDocument[];
  /** Total documents matching the filters across all pages. */
  total: number;
  /** The 1-based page number echoed back. */
  page: number;
  /** The page size echoed back. */
  page_size: number;
}

// ---------------------------------------------------------------------------
// Document editing — taxonomy and patch types (Wave 8/9 — Document page)
// ---------------------------------------------------------------------------

/**
 * A correspondent, document type, or tag as returned by the taxonomy endpoints.
 *
 * Mirrors `TaxonomyItemResponse` in `wire.py`. The same shape is used for all
 * three taxonomy lists — `GET /api/correspondents`, `GET /api/document-types`,
 * and `GET /api/tags` — to keep the frontend uniform.
 */
export interface TaxonomyItem {
  id: number;
  name: string;
  document_count: number;
}

/**
 * Optional fields for `PATCH /api/documents/{id}`.
 *
 * - Omit a field to leave it unchanged.
 * - Pass `null` to clear it on Paperless-ngx.
 *
 * The backend distinguishes "absent" from "explicit null" via Pydantic's
 * `model_fields_set`. Only the fields present in the request body are
 * forwarded to Paperless; absent fields are left untouched.
 */
export interface DocumentPatch {
  title?: string | null;
  correspondent_id?: number | null;
  document_type_id?: number | null;
  document_date?: string | null;
  tags?: number[];
  notes?: string | null;
  archive_serial_number?: number | null;
}
