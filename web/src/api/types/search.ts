/**
 * Search-pipeline wire types. Field names match `src/search/wire/search.py` and
 * `src/search/wire/stream.py` exactly; a divergence is a bug.
 */

/** Optional filters supplied in a search request. */
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

/** A single taxonomy entry as returned to the browser. */
export interface TaxonomyEntry {
  kind: string;
  id: number;
  name: string;
}

/**
 * Qualitative relevance of a search hit, from absolute vector similarity. The UI
 * shows this instead of the rank-based score, which looks misleadingly tiny.
 */
export type RelevanceTier = 'strong' | 'good' | 'partial' | 'weak';

/**
 * The looser document shape the preview viewer accepts, so Library and Index can
 * open it with a locally built object that has no `paperless_url`.
 */
export interface PreviewableDocument {
  document_id: number;
  title: string | null;
  correspondent: string | null;
  document_type: string | null;
  created: string | null;
  snippet: string;
  /** Deep link into the Paperless web UI; null hides the "Open in Paperless" action. */
  paperless_url: string | null;
  score: number;
  /** Present on search results, absent on locally built Library/Index documents. */
  relevance_tier?: RelevanceTier;
}

/** One ranked source document in the search response (`SourceDocumentResponse`). */
export interface SourceDocument extends PreviewableDocument {
  paperless_url: string;
  relevance_tier: RelevanceTier;
  /** Optional because the backend does not emit `tags`; this forces a `?? []` guard. */
  tags?: string[];
}

/**
 * One planned search in the query plan (`SpecResponse`).
 *
 * The filters are the planner's free-text guesses, not resolved taxonomy ids
 * (the `resolve` phase does that). `semantic` is null for a keyword-only spec;
 * `keywords` is empty for a semantic-only one.
 */
export interface Spec {
  mode: string;
  semantic: string | null;
  keywords: string[];
  correspondent: string | null;
  document_type: string | null;
  tags: string[];
  date_from: string | null;
  date_to: string | null;
  rationale: string;
}

/** The multi-spec query plan, shown for transparency. */
export interface QueryPlan {
  specs: Spec[];
}

/** Execution statistics for UI transparency and debugging. */
export interface SearchStats {
  llm_calls: number;
  latency_ms: number;
  refined: boolean;
}

/**
 * Token counts for one or more LLM calls. `reasoning` is a subset of `completion`
 * (it bills as output), so never add it to a cost separately.
 */
export interface TokenUsage {
  prompt: number;
  completion: number;
  reasoning: number;
  total: number;
}

/**
 * A priced cost for one phase or call. `usd` is `null` for an unpriced model;
 * `local` is `true` for a local (Ollama) provider, where the cost really is zero.
 */
export interface Cost {
  usd: number | null;
  local: boolean;
}

/** The pipeline phases in execution order; `cache` appears only on a cache hit. */
export type SearchPhase =
  | 'plan'
  | 'resolve'
  | 'retrieve'
  | 'gate'
  | 'judge'
  | 'synthesise'
  | 'replan'
  | 'refine'
  | 'cache';

/**
 * One completed pipeline phase. `tokens`/`cost` are `null` for the non-LLM phases
 * (retrieve, gate, cache); `detail` is a free-form per-phase map.
 */
export interface PhaseRecord {
  phase: SearchPhase;
  label: string;
  detail: Record<string, unknown>;
  tokens: TokenUsage | null;
  cost: Cost | null;
  ms: number;
}

/** The ordered per-phase trace assembled during a search. */
export interface SearchTrace {
  phases: PhaseRecord[];
}

/**
 * Whole-query token and dollar-cost totals.
 *
 * `usd` is `null` when any call was unpriced and not local, since no honest total
 * exists; `local` is `true` when every billed call was local.
 */
export interface CostSummary {
  tokens: TokenUsage;
  usd: number | null;
  local: boolean;
  llm_calls: number;
  /** Date of the price table used (YYYY-MM-DD), or null / absent when unknown. */
  prices_as_of?: string | null;
  /** Source of the price table: `"bundled"` or a URL. Absent on older responses. */
  prices_source?: string;
}

// NDJSON stream events — one JSON object per line from POST /api/search/stream
/** A phase has begun, emitted before its work runs (`type: "phase_start"`). */
export interface PhaseStartEvent {
  type: 'phase_start';
  seq: number;
  phase: SearchPhase;
  label: string;
}

/** A phase has completed (`type: "phase_done"`), with its `PhaseRecord` fields inline. */
export interface PhaseDoneEvent extends PhaseRecord {
  type: 'phase_done';
  seq: number;
}

/** The terminal success frame carrying the full search response (`type: "result"`). */
export interface ResultEvent {
  type: 'result';
  seq: number;
  result: SearchResponse;
}

/** A terminal failure frame (`type: "error"`). `kind` is a coarse machine code. */
export interface ErrorEvent {
  type: 'error';
  seq: number;
  kind: string;
  message: string;
}

/** One decoded NDJSON frame from the search stream. Branch on `type`. */
export type StreamEvent =
  | PhaseStartEvent
  | PhaseDoneEvent
  | ResultEvent
  | ErrorEvent;

/**
 * The kind of search result. For `clarify` (query too vague) and `no_match`
 * (retrieval too weak) `answer` carries a nudge and `sources` is empty.
 */
export type OutcomeKind = 'answered' | 'clarify' | 'no_match';

/**
 * Why a search returned nothing: no candidates retrieved, all below the relevance
 * gate, or all rejected by the judge.
 */
export type NoMatchReason = 'empty_retrieval' | 'weak_relevance' | 'judge_rejected';

/** Response body for POST /api/search. */
export interface SearchResponse {
  answer: string;
  sources: SourceDocument[];
  plan: QueryPlan;
  stats: SearchStats;
  /** The per-phase reasoning trace; `phases` is empty for a clarify short-circuit. */
  trace: SearchTrace;
  cost: CostSummary;
  outcome_kind: OutcomeKind;
  /** Set only when `outcome_kind` is `"no_match"`. */
  no_match_reason?: NoMatchReason | null;
  /** How many candidates the judge rejected; only meaningful for `"judge_rejected"`. */
  candidate_count?: number | null;
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

/** One entry in the signed-in user's recent-search history. */
export interface RecentSearch {
  query: string;
  /** ISO-8601 UTC timestamp of when the search ran. */
  created_at: string;
}

/** Response body for GET /api/recent-searches — newest entry first. */
export interface RecentSearchesResponse {
  searches: RecentSearch[];
}
