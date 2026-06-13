/**
 * Search-trace phase rendering — public surface.
 *
 * The live `LoadingScreen` rail and the folded `SearchTracePanel` map the
 * streamed `PhaseRecord[]` onto `PipelineStages` rows through `phaseToStages`,
 * and the answer-card footer formats the whole-query spend through
 * `formatSummaryCostLabel`. This module is the stable barrel those callers (and
 * the trace tests) import from; the implementation is split across three
 * siblings so each lands under the §3.1 file-length ceiling (FE-01):
 *
 *   - `costFormat`      — pure token/cost/ordinal/elapsed formatters
 *   - `detailAccessors` — defensive wire-JSON readers + `verdictsOf`
 *   - `phaseRender`     — per-phase node builders + `phaseToStages`
 *
 * Re-exporting here keeps the consumers' import paths unchanged while the
 * concerns live apart.
 */

export {
  compactTokens,
  formatUsd,
  formatCostLabel,
  formatSummaryCostLabel,
  ordinal,
  formatElapsed,
} from './costFormat';

export { verdictsOf } from './detailAccessors';

export {
  phaseSummary,
  phaseBodyNode,
  phaseDetailNode,
  phaseToStages,
} from './phaseRender';
