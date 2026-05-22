/**
 * Wire types mirroring the Python Pydantic models in `src/search/wire.py`.
 *
 * These types are the cross-language contract between the React SPA and the
 * FastAPI server. Field names and optionality MUST mirror `wire.py` exactly —
 * a divergence is a bug, not a style choice (CODE_GUIDELINES §12.6).
 *
 * Python `X | None` with no default → TypeScript `field: X | null`.
 * Python `X | None = None`          → TypeScript `field?: X | null`.
 * Python `list[X] = Field(default_factory=list)` → TypeScript `field: X[]`.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

// ---------------------------------------------------------------------------
// Account & auth types (Wave 1 — Accounts)
// ---------------------------------------------------------------------------

/** A user account, as returned by the server. Mirrors the Wave 1 contract. */
export interface User {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  role: 'admin' | 'member' | 'readonly';
  status: 'active' | 'suspended';
  created_at: string;
  last_login_at: string | null;
}

/** Response body for GET /api/setup/status. */
export interface SetupStatus {
  /** True when no users exist yet — the first-run setup screen must show. */
  needed: boolean;
}

/** Body for POST /api/setup — create the first admin account. */
export interface SetupRequest {
  /** The setup token printed to the container logs. */
  token: string;
  /** Desired admin username. */
  username: string;
  /** Desired admin password. */
  password: string;
}

/** Response body for POST /api/setup — the freshly created admin. */
export interface SetupResponse {
  user: User;
}

/** Body for POST /api/auth/login. */
export interface LoginRequest {
  username: string;
  password: string;
  /** "Keep me signed in for 7 days" — extends the session TTL. */
  remember: boolean;
}

/** Response body for POST /api/auth/login. */
export interface LoginResponse {
  user: User;
}

/** Response body for GET /api/auth/me — the current user. */
export interface MeResponse {
  user: User;
}

/** Response body for GET /api/stats/public — splash counts only. */
export interface PublicStats {
  document_count: number;
  chunk_count: number;
}

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

/** One ranked source document in the search response. */
export interface SourceDocument {
  document_id: number;
  title: string | null;
  correspondent: string | null;
  document_type: string | null;
  created: string | null;
  snippet: string;
  paperless_url: string;
  score: number;
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
// Top-level response types
// ---------------------------------------------------------------------------

/** Response body for POST /api/search. */
export interface SearchResponse {
  answer: string;
  sources: SourceDocument[];
  plan: QueryPlan;
  stats: SearchStats;
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
