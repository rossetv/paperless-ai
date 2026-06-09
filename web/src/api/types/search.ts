/**
 * Search-pipeline wire types — request, response sub-types, and facets.
 *
 * Mirrors `SearchRequest`, `SearchResponse`, `SourceDocumentResponse`,
 * `FacetsResponse` from the backend's `wire.py`. Field names are kept in
 * exact correspondence — a divergence is a bug, not a style choice.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

// ---------------------------------------------------------------------------
// Search request types
// ---------------------------------------------------------------------------

/** Optional filters supplied in a search request (spec §7.1). */
export interface FilterRequest {
  date_from?: string | null;
  date_to?: string | null;
  correspondent_id?: number | null;
  document_type_id?: number | null;
  tag_ids: number[];
}

/** Body for POST /api/search. */
export interface SearchRequest {
  query: string;
  filters?: FilterRequest | null;
}

// ---------------------------------------------------------------------------
// Response sub-types
// ---------------------------------------------------------------------------

/** A single taxonomy entry as returned to the browser. */
export interface TaxonomyEntry {
  kind: string;
  id: number;
  name: string;
}

/**
 * Qualitative relevance of a search hit, from the backend's absolute vector
 * similarity. Rendered as the `RelevanceMeter` badge (a 4-dot meter + label)
 * in place of the raw rank-based score, which read as a misleadingly tiny
 * number even for a perfect match.
 */
export type RelevanceTier = 'strong' | 'good' | 'partial' | 'weak';

/**
 * The superset document shape accepted by the preview viewer.
 *
 * Library and Index screens fabricate a local object to open the viewer —
 * they do not have a deep-link URL, so `paperless_url` is `string | null`
 * here. The wire-strict `SourceDocument` (below) extends this with a
 * non-nullable `paperless_url: string` matching the backend wire contract.
 *
 * `DocumentPreviewScreen` and `DocumentViewerChrome` accept this looser
 * interface so both fabricated and wire-originated documents can be previewed
 * without type assertions.
 */
export interface PreviewableDocument {
  document_id: number;
  title: string | null;
  correspondent: string | null;
  document_type: string | null;
  created: string | null;
  snippet: string;
  /**
   * The deep-link URL to the document in the Paperless web UI.
   *
   * Null when the URL is not available (e.g. Library/Index preview). The
   * `DocumentViewerChrome` omits the "Open in Paperless" action when null.
   */
  paperless_url: string | null;
  score: number;
  /**
   * Qualitative match strength, present on search results (`SourceDocument`)
   * and absent on locally-fabricated Library/Index documents.
   */
  relevance_tier?: RelevanceTier;
}

/**
 * One ranked source document in the search response.
 *
 * Wire-strict: mirrors `SourceDocumentResponse` in `wire.py` exactly.
 * `paperless_url` is a non-nullable `str` on the backend — the search API
 * always resolves the public Paperless URL before returning results.
 * `tags` is a flat list of tag name strings returned by the backend.
 *
 * Screens that fabricate a local document object (Library, Index) use
 * `PreviewableDocument` instead and supply `null` for `paperless_url`.
 */
export interface SourceDocument extends PreviewableDocument {
  paperless_url: string;
  /** A search result always carries a relevance tier (required override). */
  relevance_tier: RelevanceTier;
  /** Tag names attached to this document, as returned by the search API. */
  tags: string[];
}

/** The query plan for UI transparency (spec §7.1). */
export interface QueryPlan {
  semantic_queries: string[];
  keyword_terms: string[];
  sub_questions: string[];
}

/** Execution statistics for UI transparency and debugging. */
export interface SearchStats {
  llm_calls: number;
  latency_ms: number;
  refined: boolean;
}

// ---------------------------------------------------------------------------
// Top-level search response types
// ---------------------------------------------------------------------------

/**
 * Discriminator for the search result type (spec §7.1).
 *
 * ``"answered"``  — the synthesiser produced a full answer with sources.
 * ``"clarify"``   — the query was too vague (Layer 1 fail-fast); `answer`
 *                   carries a nudge message and `sources` is empty.
 * ``"no_match"``  — retrieval was too weak (Layer 2 fail-fast); `answer`
 *                   carries a nudge message and `sources` is empty.
 */
export type OutcomeKind = 'answered' | 'clarify' | 'no_match';

/** Response body for POST /api/search. */
export interface SearchResponse {
  answer: string;
  sources: SourceDocument[];
  plan: QueryPlan;
  stats: SearchStats;
  /** Discriminator for the result type — branch on this in the UI. */
  outcome_kind: OutcomeKind;
}

/** Response body for GET /api/facets. */
export interface FacetsResponse {
  correspondents: TaxonomyEntry[];
  document_types: TaxonomyEntry[];
  tags: TaxonomyEntry[];
  earliest: string | null;
  latest: string | null;
}

/** Response body for GET /api/stats. */
export interface StatsResponse {
  document_count: number;
  chunk_count: number;
  last_reconcile_at: string | null;
  embedding_model: string | null;
}

/** Response body for GET /api/healthz. */
export interface StatusResponse {
  status: string;
}

// ---------------------------------------------------------------------------
// Recent searches (Wave 2 — Search redesign)
// ---------------------------------------------------------------------------

/**
 * One entry in the signed-in user's recent-search history.
 *
 * Mirrors `RecentSearchEntry` in `src/search/wire.py`: a row of the
 * `recent_searches` table added by the Wave 2 backend (`app.db` migration
 * v2). `created_at` is an ISO-8601 UTC timestamp.
 */
export interface RecentSearch {
  /** The raw query text the user searched for. */
  query: string;
  /** ISO-8601 UTC timestamp of when the search ran. */
  created_at: string;
}

/** Response body for GET /api/recent-searches — newest entry first. */
export interface RecentSearchesResponse {
  searches: RecentSearch[];
}
