/** Token and cost chip labels for the live rail, trace panel and answer footer. */

import type { Cost, CostSummary, TokenUsage } from '../../../api/types';

/** Compact a token count: 1234 → "1.2k", 980 → "980", 12000 → "12k". */
export function compactTokens(total: number): string {
  if (total < 1000) {
    return String(total);
  }
  const thousands = total / 1000;
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
 * The whole-query "tokens · cost" label (e.g. "29k tok · $0.07"), with the same
 * cost rules as `formatCostLabel`. Undefined when no LLM call was made.
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

/** 1 → "1st", 2 → "2nd", 11 → "11th", 21 → "21st". */
export function ordinal(n: number): string {
  const abs = Math.abs(n);
  const mod100 = abs % 100;
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
 * Elapsed milliseconds as `m:ss` (92 000 → "1:32"). A clock that ran backwards
 * reads "0:00".
 */
export function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}
