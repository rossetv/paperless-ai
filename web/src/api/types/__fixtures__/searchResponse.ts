/**
 * Shared test fixtures for the `trace`/`cost` fields added to `SearchResponse`.
 *
 * Every test that builds a `SearchResponse` literal needs the two telemetry
 * fields. Rather than repeat the same empty `SearchTrace`/`CostSummary` literal
 * in each test file (and have them drift), expose one shared default here and
 * spread it into the fixture: `{ ...EMPTY_TELEMETRY, answer: …, sources: … }`.
 *
 * Test-only — not shipped in the app bundle.
 */

import type { CostSummary, SearchTrace } from '../search';

/** An empty trace — no phases recorded. */
export const EMPTY_TRACE: SearchTrace = { phases: [] };

/** A zero-cost summary with no honest dollar total (unknown, non-local). */
export const EMPTY_COST: CostSummary = {
  tokens: { prompt: 0, completion: 0, reasoning: 0, total: 0 },
  usd: null,
  local: false,
  llm_calls: 0,
};

/**
 * The two telemetry fields a bare `SearchResponse` fixture must now carry.
 * Spread first, then override the meaningful fields for the test.
 */
export const EMPTY_TELEMETRY: { trace: SearchTrace; cost: CostSummary } = {
  trace: EMPTY_TRACE,
  cost: EMPTY_COST,
};
