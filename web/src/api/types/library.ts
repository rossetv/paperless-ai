/** Library list, document metadata, taxonomy and document-patch wire types. */

/**
 * Sort field for GET /api/documents. `added` is when the document was indexed
 * (`indexed_at`); `created` is the document's own creation date.
 */
export type DocumentSortField = 'created' | 'title' | 'added';

/** Query parameters for GET /api/documents; nullish filters are left out of the URL. */
export interface DocumentsQuery {
  /** 1-based page number. */
  page: number;
  page_size: number;
  sort: DocumentSortField;
  /** True for descending order (newest/largest first); false for ascending. */
  descending: boolean;
  /** Free-text filter over title / correspondent / type. */
  query?: string | null;
  correspondent_id?: number | null;
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
  id: number;
  /** Document title; null when Paperless has none. */
  title: string | null;
  /** Correspondent name; null when unset. */
  correspondent: string | null;
  /** Document-type name; null when unset. */
  document_type: string | null;
  /** Creation date as ISO-8601; null when unknown. */
  created: string | null;
  tags: string[];
  /** Number of pages in the document; null when the page count is unknown. */
  page_count: number | null;
  /** Deep-link URL into Paperless-ngx for this document. */
  paperless_url: string;
}

/** Response body for GET /api/documents. */
export interface DocumentsResponse {
  documents: LibraryDocument[];
  /** Total documents matching the filters across all pages. */
  total: number;
  /** The 1-based page number echoed back. */
  page: number;
  page_size: number;
}

/** A correspondent, document type or tag; all three taxonomy endpoints share this shape. */
export interface TaxonomyItem {
  id: number;
  name: string;
  document_count: number;
}

/**
 * Optional fields for `PATCH /api/documents/{id}`: omit a field to leave it
 * unchanged, pass `null` to clear it. The backend tells the two apart with
 * Pydantic's `model_fields_set`.
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
