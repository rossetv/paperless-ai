/**
 * Shared rendering of search-trace phases as `PipelineStages` rows.
 *
 * The live `LoadingScreen` rail and the folded `SearchTracePanel` show the SAME
 * per-phase information — the planner's rewritten query, the retrieval counts,
 * the vector-gate outcome, the judge's per-document verdicts, the synthesis
 * mode, plus a token/cost chip on every LLM phase. This module is the single
 * source of that mapping, so the two surfaces never drift.
 *
 * `phaseToStages(records, activePhase)` turns the streamed `PhaseRecord[]` (plus
 * the currently-running phase, if any) into `PipelineStage[]`. A record's
 * free-form `detail` map is read defensively: a missing or wrong-typed key
 * simply renders nothing rather than throwing, since `detail` is wire JSON.
 *
 * Allowed deps: react, api/types, components/primitives (PipelineStages types),
 * components/primitives (Text) (CODE_GUIDELINES §12.3).
 */

import React from 'react';
import type {
  Cost,
  CostSummary,
  PhaseRecord,
  SearchPhase,
  TokenUsage,
} from '../../../api/types';
import type {
  PipelineStage,
  PipelineStageState,
  StageVerdict,
} from '../../../components/primitives/PipelineStages/PipelineStages';

/** A human-readable label for each phase, used when streaming a `phase_start`
 *  before its done-record (which carries the server's own label) arrives. */
const PHASE_LABELS: Record<SearchPhase, string> = {
  plan: 'Planning the query',
  retrieve: 'Retrieving documents',
  gate: 'Relevance gate',
  judge: 'Judging relevance',
  synthesise: 'Synthesising the answer',
  refine: 'Refining the answer',
  cache: 'Served from cache',
};

// ---------------------------------------------------------------------------
// Defensive detail accessors — `detail` is free-form wire JSON.
// ---------------------------------------------------------------------------

function str(detail: Record<string, unknown>, key: string): string | null {
  const value = detail[key];
  return typeof value === 'string' ? value : null;
}

function num(detail: Record<string, unknown>, key: string): number | null {
  const value = detail[key];
  return typeof value === 'number' ? value : null;
}

function bool(detail: Record<string, unknown>, key: string): boolean {
  return detail[key] === true;
}

/** Read the judge's per-document verdicts from a judge phase's `detail`. */
export function verdictsOf(record: PhaseRecord): StageVerdict[] | undefined {
  if (record.phase !== 'judge') {
    return undefined;
  }
  const raw = record.detail['verdicts'];
  if (!Array.isArray(raw)) {
    return undefined;
  }
  return raw.map((entry): StageVerdict => {
    const item = (entry ?? {}) as Record<string, unknown>;
    return {
      docId: typeof item['doc_id'] === 'number' ? item['doc_id'] : 0,
      title: typeof item['title'] === 'string' ? item['title'] : null,
      keep: item['keep'] === true,
      reason: typeof item['reason'] === 'string' ? item['reason'] : '',
    };
  });
}

// ---------------------------------------------------------------------------
// Token / cost formatting
// ---------------------------------------------------------------------------

/** Compact a token count: 1234 → "1.2k", 980 → "980", 12000 → "12k". */
export function compactTokens(total: number): string {
  if (total < 1000) {
    return String(total);
  }
  const thousands = total / 1000;
  // One decimal below 10k (1.2k), none above (12k) — keeps the chip short.
  const text =
    thousands < 10 ? thousands.toFixed(1) : String(Math.round(thousands));
  return `${text.replace(/\.0$/, '')}k`;
}

/** Format a dollar cost: $0 for zero, a precise small figure otherwise. */
export function formatUsd(usd: number): string {
  if (usd === 0) {
    return '$0';
  }
  if (usd >= 1) {
    return `$${usd.toFixed(2)}`;
  }
  // Sub-dollar: up to 4 decimals, trailing zeros trimmed (0.0040 → "$0.004").
  const trimmed = usd.toFixed(4).replace(/0+$/, '').replace(/\.$/, '');
  // A positive cost that rounds to $0.0000 still gets an honest floor.
  return trimmed === '0' ? '<$0.0001' : `$${trimmed}`;
}

/**
 * A compact "tokens · cost" label for an LLM phase, or undefined for a non-LLM
 * phase (which carries no tokens). Local provider → "$0"; unpriced usd → "—".
 */
export function formatCostLabel(
  tokens: TokenUsage | null,
  cost: Cost | null,
): string | undefined {
  if (tokens === null) {
    return undefined;
  }
  const tokensPart = `${compactTokens(tokens.total)} tok`;
  let costPart: string;
  if (cost === null) {
    costPart = '—';
  } else if (cost.local) {
    costPart = '$0';
  } else if (cost.usd === null) {
    costPart = '—';
  } else {
    costPart = formatUsd(cost.usd);
  }
  return `${tokensPart} · ${costPart}`;
}

/**
 * The whole-query "tokens · cost" label from a `CostSummary` (the answer-card
 * footer and the trace-panel summary). Shows "$0" for an all-local query and
 * "—" when the spend cannot be honestly priced; returns undefined when no LLM
 * call was made (zero tokens AND zero calls — nothing worth showing).
 */
export function formatSummaryCostLabel(
  summary: CostSummary,
): string | undefined {
  if (summary.tokens.total === 0 && summary.llm_calls === 0) {
    return undefined;
  }
  return formatCostLabel(summary.tokens, {
    usd: summary.usd,
    local: summary.local,
  });
}

// ---------------------------------------------------------------------------
// Per-phase detail node
// ---------------------------------------------------------------------------

/**
 * The rich detail node for one phase, rendered under its label. Returns null
 * when there is nothing useful to show (the row then falls back to its plain
 * `detail` string, which is empty for live phases).
 */
export function phaseDetailNode(record: PhaseRecord): React.ReactNode {
  const d = record.detail;
  switch (record.phase) {
    case 'plan': {
      const rewritten = str(d, 'rewritten_query');
      if (bool(d, 'skipped_trivial')) {
        return 'Trivial query — planning skipped';
      }
      return rewritten ? `Rewritten: “${rewritten}”` : null;
    }
    case 'retrieve': {
      const chunks = num(d, 'chunk_count');
      const docs = num(d, 'doc_count');
      if (chunks === null && docs === null) {
        return null;
      }
      const broadened = bool(d, 'broadened') ? ' · broadened' : '';
      return `${chunks ?? 0} chunks · ${docs ?? 0} documents${broadened}`;
    }
    case 'gate': {
      const evaluated = num(d, 'evaluated');
      if (bool(d, 'rejected')) {
        return 'Rejected — retrieval too weak';
      }
      const best = num(d, 'best_similarity');
      const bestText = best !== null ? ` · best ${best.toFixed(2)}` : '';
      return evaluated !== null
        ? `Passed ${evaluated} documents${bestText}`
        : null;
    }
    case 'judge': {
      const verdicts = verdictsOf(record) ?? [];
      const kept = verdicts.filter((v) => v.keep).length;
      const dropped = verdicts.length - kept;
      if (bool(d, 'degraded')) {
        return 'Judge unavailable — kept all (fail-open)';
      }
      if (bool(d, 'bailed')) {
        return 'No document judged relevant';
      }
      if (verdicts.length === 0) {
        return null;
      }
      return `Kept ${kept}, dropped ${dropped}`;
    }
    case 'synthesise': {
      const mode = str(d, 'mode');
      const needsMore = bool(d, 'needs_more') ? ' · needs more context' : '';
      return mode ? `Mode: ${mode}${needsMore}` : null;
    }
    case 'refine': {
      const pass = num(d, 'pass');
      const adjustment = str(d, 'adjustment');
      if (pass === null && adjustment === null) {
        return null;
      }
      return adjustment
        ? `Pass ${pass ?? 1}: ${adjustment}`
        : `Pass ${pass ?? 1}`;
    }
    case 'cache':
      return 'Answer served from the cache';
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Phase → stage mapping
// ---------------------------------------------------------------------------

/**
 * Map the streamed phases onto `PipelineStage[]` for the rail / trace panel.
 *
 * Each completed `PhaseRecord` becomes a `done` row with its detail node, cost
 * chip and (for judge) verdict sublist. When `activePhase` is set and has not
 * yet produced a record, a trailing `active` row is appended so the rail shows
 * the in-flight phase "in progress". Pass `activePhase = null` for a finished
 * trace (every row `done`).
 *
 * @param records     The completed phases, in order.
 * @param activePhase The phase currently running, or null.
 */
export function phaseToStages(
  records: PhaseRecord[],
  activePhase: SearchPhase | null,
): PipelineStage[] {
  const stages: PipelineStage[] = records.map((record) => {
    const state: PipelineStageState = 'done';
    const detailNode = phaseDetailNode(record);
    const costLabel = formatCostLabel(record.tokens, record.cost);
    const verdicts = verdictsOf(record);
    return {
      label: record.label,
      detail: '',
      state,
      ...(detailNode !== null ? { detailNode } : {}),
      ...(costLabel !== undefined ? { costLabel } : {}),
      ...(verdicts !== undefined ? { verdicts } : {}),
    };
  });

  // Append the in-flight phase as an active row when it has no record yet. The
  // last recorded phase can equal activePhase only transiently; the reducer
  // clears activePhase on phase_done, so a duplicate row cannot persist.
  if (activePhase !== null) {
    stages.push({
      label: PHASE_LABELS[activePhase],
      detail: '',
      state: 'active',
    });
  }

  return stages;
}
