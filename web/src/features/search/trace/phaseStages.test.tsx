import { describe, it, expect } from 'vitest';
import {
  compactTokens,
  formatCostLabel,
  formatUsd,
  phaseToStages,
  verdictsOf,
} from './phaseStages';
import type { PhaseRecord } from '../../../api/types';

describe('compactTokens', () => {
  it('shows an exact count below 1000', () => {
    expect(compactTokens(0)).toBe('0');
    expect(compactTokens(980)).toBe('980');
  });

  it('shows one decimal between 1k and 10k', () => {
    expect(compactTokens(1240)).toBe('1.2k');
    expect(compactTokens(1000)).toBe('1k');
  });

  it('rounds to whole thousands at and above 10k', () => {
    expect(compactTokens(12000)).toBe('12k');
    expect(compactTokens(12400)).toBe('12k');
  });
});

describe('formatUsd', () => {
  it('shows $0 for an exact zero', () => {
    expect(formatUsd(0)).toBe('$0');
  });

  it('trims trailing zeros on a sub-dollar cost', () => {
    expect(formatUsd(0.004)).toBe('$0.004');
    expect(formatUsd(0.25)).toBe('$0.25');
  });

  it('keeps two decimals at or above a dollar', () => {
    expect(formatUsd(1)).toBe('$1.00');
    expect(formatUsd(3.5)).toBe('$3.50');
  });

  it('floors a positive cost that rounds below the display precision', () => {
    expect(formatUsd(0.00001)).toBe('<$0.0001');
  });
});

describe('formatCostLabel', () => {
  it('returns undefined for a non-LLM phase (no tokens)', () => {
    expect(formatCostLabel(null, null)).toBeUndefined();
  });

  it('combines tokens and a priced cost', () => {
    expect(
      formatCostLabel(
        { prompt: 1200, completion: 40, reasoning: 0, total: 1240 },
        { usd: 0.004, local: false },
      ),
    ).toBe('1.2k tok · $0.004');
  });

  it('shows $0 for a local provider', () => {
    expect(
      formatCostLabel(
        { prompt: 10, completion: 20, reasoning: 0, total: 30 },
        { usd: 0, local: true },
      ),
    ).toBe('30 tok · $0');
  });

  it('shows — for an unpriced (null usd) cost', () => {
    expect(
      formatCostLabel(
        { prompt: 10, completion: 20, reasoning: 0, total: 30 },
        { usd: null, local: false },
      ),
    ).toBe('30 tok · —');
  });

  it('shows — when the phase has tokens but a null cost', () => {
    expect(
      formatCostLabel(
        { prompt: 10, completion: 20, reasoning: 0, total: 30 },
        null,
      ),
    ).toBe('30 tok · —');
  });
});

describe('verdictsOf', () => {
  it('returns undefined for a non-judge phase', () => {
    const record: PhaseRecord = {
      phase: 'retrieve',
      label: 'Retrieving',
      detail: {},
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(verdictsOf(record)).toBeUndefined();
  });

  it('maps wire verdicts (doc_id) to stage verdicts (docId)', () => {
    const record: PhaseRecord = {
      phase: 'judge',
      label: 'Judging',
      detail: {
        verdicts: [
          { doc_id: 9823, title: 'A', keep: true, reason: 'yes' },
          { doc_id: 4410, title: null, keep: false, reason: 'no' },
        ],
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(verdictsOf(record)).toEqual([
      { docId: 9823, title: 'A', keep: true, reason: 'yes' },
      { docId: 4410, title: null, keep: false, reason: 'no' },
    ]);
  });

  it('tolerates a malformed verdicts value', () => {
    const record: PhaseRecord = {
      phase: 'judge',
      label: 'Judging',
      detail: { verdicts: 'not-an-array' },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(verdictsOf(record)).toBeUndefined();
  });
});

describe('phaseToStages', () => {
  const planRecord: PhaseRecord = {
    phase: 'plan',
    label: 'Planning the query',
    detail: { rewritten_query: 'npower 2024', skipped_trivial: false },
    tokens: { prompt: 100, completion: 10, reasoning: 0, total: 110 },
    cost: { usd: 0.001, local: false },
    ms: 12,
  };

  it('maps completed records to done stages with cost chips', () => {
    const stages = phaseToStages([planRecord], null);
    expect(stages).toHaveLength(1);
    expect(stages[0]?.state).toBe('done');
    expect(stages[0]?.costLabel).toBe('110 tok · $0.001');
    expect(stages[0]?.detailNode).toBeTruthy();
  });

  it('appends an active row for the in-flight phase', () => {
    const stages = phaseToStages([planRecord], 'retrieve');
    expect(stages).toHaveLength(2);
    expect(stages[1]?.state).toBe('active');
    expect(stages[1]?.label).toBe('Retrieving documents');
  });

  it('produces an all-done trace when activePhase is null', () => {
    const stages = phaseToStages([planRecord], null);
    expect(stages.every((s) => s.state === 'done')).toBe(true);
  });
});
