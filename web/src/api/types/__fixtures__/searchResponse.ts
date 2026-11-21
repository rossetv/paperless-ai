/**
 * Test-only defaults for the `trace` and `cost` fields every `SearchResponse`
 * fixture needs: `{ ...EMPTY_TELEMETRY, answer: …, sources: … }`.
 */

import type { CostSummary, SearchTrace } from '../search';

export const EMPTY_TRACE: SearchTrace = { phases: [] };

/** A zero-cost summary with no honest dollar total (unknown, non-local). */
export const EMPTY_COST: CostSummary = {
  tokens: { prompt: 0, completion: 0, reasoning: 0, total: 0 },
  usd: null,
  local: false,
  llm_calls: 0,
};

export const EMPTY_TELEMETRY: { trace: SearchTrace; cost: CostSummary } = {
  trace: EMPTY_TRACE,
  cost: EMPTY_COST,
};
