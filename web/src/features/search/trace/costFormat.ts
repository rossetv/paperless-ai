/**
 * Token / cost formatting for the search-trace surfaces.
 *
 * Pure, unit-testable helpers that turn a phase's (or a whole query's) token
 * usage and priced cost into the compact chip labels shown on the live rail,
 * the folded trace panel and the answer-card footer. No React, no wire-JSON
 * shapes — just numbers in, display strings out. Split out of `phaseStages`
 * (FE-01) so the per-phase renderer stays under the file-length ceiling.
 *
 * Allowed deps: api/types only (CODE_GUIDELINES §12.3).
 */

import type { Cost, CostSummary, TokenUsage } from '../../../api/types';

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
 * The whole-query aggregate label from a `CostSummary` — tokens · cost (e.g.
 * "29k tok · $0.07"). Shown on the answer card footer and the "How this answer
 * was found" trace header so the user sees the total spend at a glance. The
 * cost segment mirrors `formatCostLabel`: a local (Ollama) provider reads "$0",
 * an unpriced total reads "—". Returns undefined when no LLM call was made
 * (zero tokens AND zero calls — nothing worth showing).
 */
export function formatSummaryCostLabel(
  summary: CostSummary,
): string | undefined {
  if (summary.tokens.total === 0 && summary.llm_calls === 0) {
    return undefined;
  }
  const tokensPart = `${compactTokens(summary.tokens.total)} tok`;
  let costPart: string;
  if (summary.local) {
    costPart = '$0';
  } else if (summary.usd === null) {
    costPart = '—';
  } else {
    costPart = formatUsd(summary.usd);
  }
  return `${tokensPart} · ${costPart}`;
}

/**
 * Return the ordinal suffix for a 1-based index: 1→"1st", 2→"2nd", 3→"3rd",
 * 4→"4th", …, 11→"11th", 12→"12th", 13→"13th", 21→"21st", etc.
 */
export function ordinal(n: number): string {
  const abs = Math.abs(n);
  const mod100 = abs % 100;
  // Special-case the teens (11–13) which break the normal suffix pattern.
  if (mod100 >= 11 && mod100 <= 13) {
    return `${n}th`;
  }
  const mod10 = abs % 10;
  if (mod10 === 1) return `${n}st`;
  if (mod10 === 2) return `${n}nd`;
  if (mod10 === 3) return `${n}rd`;
  return `${n}th`;
}

/**
 * Format a wall-clock elapsed duration (milliseconds) as `m:ss` — e.g. 9 000 →
 * "0:09", 92 000 → "1:32". Driven from a real start timestamp by the live rail
 * so the counter tracks true elapsed time rather than per-frame increments.
 * Negative input is floored to zero (a clock that ran backwards reads "0:00").
 */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}
