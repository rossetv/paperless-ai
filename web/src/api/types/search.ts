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

/**
 * One planned search in the multi-spec plan, for UI transparency (spec §7.1).
 *
 * Mirrors `SpecResponse` in `wire/search.py`: the planner's free-text filter
 * *guesses* (correspondent / document_type / tags / date bounds), NOT the
 * resolved taxonomy ids — resolution happens later in the pipeline (the
 * `resolve` phase). `semantic` is null for a keyword-only spec; `keywords` is
 * empty for a semantic-only spec.
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

/** The multi-spec query plan for UI transparency (spec §7.1). */
export interface QueryPlan {
  specs: Spec[];
}

/** Execution statistics for UI transparency and debugging. */
export interface SearchStats {
  llm_calls: number;
  latency_ms: number;
  refined: boolean;
}

// ---------------------------------------------------------------------------
// Trace + cost telemetry (Wave — live reasoning trace + token/cost)
// ---------------------------------------------------------------------------

/**
 * Token counts for one or more LLM calls.
 *
 * Mirrors `TokenUsageResponse` in `wire/search.py`. `reasoning` is a SUBSET of
 * `completion` (reasoning tokens bill as output) — never add it to a cost
 * separately; `total` is the API's `total_tokens`.
 */
export interface TokenUsage {
  prompt: number;
  completion: number;
  reasoning: number;
  total: number;
}

/**
 * A priced cost for one phase or one call.
 *
 * Mirrors `CostResponse`. `usd` is `null` for an unknown/unpriced model (the UI
 * shows "—"); `local` is `true` for a local (Ollama) provider, where the cost
 * is genuinely zero.
 */
export interface Cost {
  usd: number | null;
  local: boolean;
}

/**
 * The pipeline phases, in execution order. `cache` is emitted only on a
 * cache-hit short-circuit. Mirrors the backend `phase` discriminator.
 */
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
 * One completed pipeline phase, for the trace.
 *
 * Mirrors `PhaseRecordResponse`. `tokens`/`cost` are `null` for the non-LLM
 * phases (retrieve, gate, cache). `detail` is a per-phase free-form map the SPA
 * renders (the planner's rewritten query, the judge's per-document verdicts, …).
 */
export interface PhaseRecord {
  phase: SearchPhase;
  label: string;
  detail: Record<string, unknown>;
  tokens: TokenUsage | null;
  cost: Cost | null;
  ms: number;
}

/** The ordered per-phase trace assembled during a search. Mirrors `SearchTraceResponse`. */
export interface SearchTrace {
  phases: PhaseRecord[];
}

/**
 * Whole-query token + dollar-cost totals. Mirrors `CostSummaryResponse`.
 *
 * `usd` is `null` when any LLM call was unpriced-and-not-local (no honest
 * total); `local` is `true` when every billed call was local.
 */
export interface CostSummary {
  tokens: TokenUsage;
  usd: number | null;
  local: boolean;
  llm_calls: number;
}

// ---------------------------------------------------------------------------
// NDJSON stream events — one JSON object per line from POST /api/search/stream
// ---------------------------------------------------------------------------

/** A phase has begun, emitted before its work runs (`type: "phase_start"`). */
export interface PhaseStartEvent {
  type: 'phase_start';
  seq: number;
  phase: SearchPhase;
  label: string;
}

/**
 * A phase has completed (`type: "phase_done"`). Carries the full `PhaseRecord`
 * fields inline alongside the frame discriminator and sequence number.
 */
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

/**
 * Machine-readable reason for a zero-result response (spec §7.1).
 *
 * ``"empty_retrieval"``  — the vector store returned no candidates for the
 *                          query (before any judge ran).
 * ``"weak_relevance"``   — candidates were retrieved but the vector similarity
 *                          scores were all below the relevance gate threshold.
 * ``"judge_rejected"``   — the judge evaluated candidates but rejected them
 *                          all as not answering the question.
 *
 * `null` when `outcome_kind` is ``"answered"`` or the backend does not supply
 * the field (older API versions).
 */
export type NoMatchReason = 'empty_retrieval' | 'weak_relevance' | 'judge_rejected';

/** Response body for POST /api/search. */
export interface SearchResponse {
  answer: string;
  sources: SourceDocument[];
  plan: QueryPlan;
  stats: SearchStats;
  /**
   * The ordered per-phase reasoning trace (mirrors `SearchResponse.trace`).
   * Always present now — empty `phases` for a Layer-1 clarify short-circuit.
   */
  trace: SearchTrace;
  /**
   * Whole-query token + cost totals (mirrors `SearchResponse.cost`). Always
   * present now; `usd` is `null` when the spend cannot be honestly priced.
   */
  cost: CostSummary;
  /** Discriminator for the result type — branch on this in the UI. */
  outcome_kind: OutcomeKind;
  /**
   * Machine-readable reason for a zero-result response.
   *
   * Present (and non-null) only when `outcome_kind` is ``"no_match"``.
   * `null` for a ``"clarify"`` or ``"answered"`` result, and absent on older
   * API responses that pre-date this field.
   */
  no_match_reason?: NoMatchReason | null;
  /**
   * Number of candidate documents evaluated by the judge before it rejected
   * them all (only meaningful when `no_match_reason` is ``"judge_rejected"``).
   *
   * `null` / absent when the count is not available (e.g. empty retrieval).
   */
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
