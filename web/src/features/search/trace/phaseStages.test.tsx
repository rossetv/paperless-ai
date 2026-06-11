import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import {
  compactTokens,
  formatCostLabel,
  formatUsd,
  phaseDetailNode,
  phaseSummary,
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
          {
            doc_id: 9823,
            title: 'A',
            keep: true,
            reason: 'yes',
            score: 0.8,
            paperless_url: 'http://paperless/documents/9823/',
          },
          { doc_id: 4410, title: null, keep: false, reason: 'no' },
        ],
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(verdictsOf(record)).toEqual([
      {
        docId: 9823,
        title: 'A',
        keep: true,
        reason: 'yes',
        score: 0.8,
        paperlessUrl: 'http://paperless/documents/9823/',
      },
      // Missing score / paperless_url map to null.
      {
        docId: 4410,
        title: null,
        keep: false,
        reason: 'no',
        score: null,
        paperlessUrl: null,
      },
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

/** Render a phase's detail node and return its text content for assertions. */
function detailText(record: PhaseRecord): string {
  const { container } = render(<>{phaseDetailNode(record)}</>);
  return container.textContent ?? '';
}

describe('phaseDetailNode — planner specs', () => {
  it('renders one line per planned spec with query, mode, filters, rationale', () => {
    const record: PhaseRecord = {
      phase: 'plan',
      label: 'Planning the query',
      detail: {
        skipped_trivial: false,
        specs: [
          {
            mode: 'hybrid',
            query: 'npower energy 2024',
            filters: {
              correspondent: 'Npower',
              document_type: 'Invoice',
              tags: ['bills'],
              date_from: '2024-01-01',
              date_to: '2024-12-31',
            },
            rationale: 'find the annual spend',
          },
        ],
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    const text = detailText(record);
    expect(text).toContain('npower energy 2024');
    expect(text).toContain('(hybrid)');
    expect(text).toContain('from Npower');
    expect(text).toContain('type Invoice');
    expect(text).toContain('tags bills');
    expect(text).toContain('2024-01-01→2024-12-31');
    expect(text).toContain('find the annual spend');
  });

  it('falls back to the legacy rewritten_query when no specs are present', () => {
    const record: PhaseRecord = {
      phase: 'plan',
      label: 'Planning the query',
      detail: { rewritten_query: 'old shape', skipped_trivial: false },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(detailText(record)).toContain('old shape');
  });

  it('reports a skipped trivial plan', () => {
    const record: PhaseRecord = {
      phase: 'plan',
      label: 'Planning the query',
      detail: { skipped_trivial: true, specs: [] },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(detailText(record)).toContain('Trivial query');
  });
});

describe('phaseDetailNode — resolve', () => {
  it('renders resolved ids/dates and the dropped guesses', () => {
    const record: PhaseRecord = {
      phase: 'resolve',
      label: 'Resolving filters',
      detail: {
        resolved: [
          {
            spec_index: 0,
            correspondent_id: 7,
            document_type_id: null,
            tag_ids: [3, 9],
            date_from: '2024-01-01',
            date_to: null,
          },
        ],
        dropped: [{ spec_index: 0, names: ['Acme Ltd', 'Receipt'] }],
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    const text = detailText(record);
    expect(text).toContain('correspondent #7');
    expect(text).toContain('tags #3, #9');
    expect(text).toContain('from 2024-01-01');
    expect(text).toContain('Dropped (no match): Acme Ltd, Receipt');
  });

  it('renders "no filters" for a spec that resolved nothing', () => {
    const record: PhaseRecord = {
      phase: 'resolve',
      label: 'Resolving filters',
      detail: {
        resolved: [
          {
            spec_index: 0,
            correspondent_id: null,
            document_type_id: null,
            tag_ids: [],
            date_from: null,
            date_to: null,
          },
        ],
        dropped: [],
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(detailText(record)).toContain('no filters');
  });
});

describe('phaseDetailNode — refine', () => {
  it('renders the gap, action, new searches, and carried-over count', () => {
    const record: PhaseRecord = {
      phase: 'refine',
      label: 'Refining',
      detail: {
        gap: 'no figure for Q4',
        action: 're-planned: 1 new searches',
        new_specs: [{ mode: 'semantic', query: 'Q4 invoice total' }],
        carried_over: 3,
        noop: false,
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    const text = detailText(record);
    expect(text).toContain('Gap: no figure for Q4');
    expect(text).toContain('Action: re-planned');
    expect(text).toContain('New search 1: “Q4 invoice total”');
    expect(text).toContain('Carried over 3 documents');
  });

  it('omits new searches on a no-op pass', () => {
    const record: PhaseRecord = {
      phase: 'refine',
      label: 'Refining',
      detail: {
        gap: 'nothing more to add',
        action: 'no new searches → finalising on current evidence',
        new_specs: [],
        carried_over: 1,
        noop: true,
      },
      tokens: null,
      cost: null,
      ms: 1,
    };
    const text = detailText(record);
    expect(text).toContain('finalising on current evidence');
    expect(text).not.toContain('New search');
    expect(text).toContain('Carried over 1 document');
  });
});

describe('phaseDetailNode — replan', () => {
  it('renders the hint and the re-planned searches', () => {
    const record: PhaseRecord = {
      phase: 'replan',
      label: 'Re-planning',
      detail: {
        hint: 'need the 2023 figure too',
        specs: [{ mode: 'hybrid', query: '2023 energy spend' }],
        clarify: false,
      },
      tokens: { prompt: 50, completion: 5, reasoning: 0, total: 55 },
      cost: { usd: 0.0005, local: false },
      ms: 1,
    };
    const text = detailText(record);
    expect(text).toContain('Hint: need the 2023 figure too');
    expect(text).toContain('2023 energy spend');
  });

  it('notes when a re-plan asked to clarify', () => {
    const record: PhaseRecord = {
      phase: 'replan',
      label: 'Re-planning',
      detail: { clarify: true },
      tokens: null,
      cost: null,
      ms: 1,
    };
    expect(detailText(record)).toContain('asked to clarify');
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

// Helper to create a plan record with N specs
function makePlanRecord(numSpecs: number): PhaseRecord {
  return {
    phase: 'plan',
    label: 'Planning the query',
    detail: {
      skipped_trivial: false,
      specs: Array.from({ length: numSpecs }, (_, i) => ({
        mode: i === 0 ? 'keyword' : 'semantic',
        query: `query ${i + 1}`,
        filters: {},
        rationale: null,
      })),
    },
    tokens: null,
    cost: null,
    ms: 1,
  };
}

function makeResolveRecord(options: {
  resolved?: Record<string, unknown>[];
  dropped?: Record<string, unknown>[];
} = {}): PhaseRecord {
  return {
    phase: 'resolve',
    label: 'Resolving filters',
    detail: {
      resolved: options.resolved ?? [],
      dropped: options.dropped ?? [],
    },
    tokens: null,
    cost: null,
    ms: 1,
  };
}

function makeRetrieveRecord(chunks: Record<string, unknown>[]): PhaseRecord {
  return {
    phase: 'retrieve',
    label: 'Retrieving documents',
    detail: {
      chunk_count: chunks.length,
      doc_count: 2,
      chunks,
    },
    tokens: null,
    cost: null,
    ms: 1,
  };
}

function makeGateRecord(documents: Record<string, unknown>[]): PhaseRecord {
  return {
    phase: 'gate',
    label: 'Relevance gate',
    detail: {
      evaluated: documents.length,
      best_similarity: documents.length > 0 ? (documents[0] as Record<string, unknown>)['best_similarity'] : null,
      documents,
    },
    tokens: null,
    cost: null,
    ms: 1,
  };
}

describe('phaseSummary', () => {
  it('plan: shows N searches planned', () => {
    const record = makePlanRecord(3);
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('3 searches planned');
    expect(container.textContent).toContain('1 keyword');
    expect(container.textContent).toContain('2 semantic');
  });

  it('plan: skipped_trivial returns the single summary string', () => {
    const record: PhaseRecord = {
      phase: 'plan',
      label: 'Planning the query',
      detail: { skipped_trivial: true, specs: [] },
      tokens: null, cost: null, ms: 1,
    };
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toMatch(/trivial/i);
  });

  it('resolve: shows N filters resolved and M dropped', () => {
    const record = makeResolveRecord({
      resolved: [
        { spec_index: 0, correspondent: { id: 7, name: 'Npower', method: 'exact' }, document_type: null, tags: [], date_from: null, date_to: null },
        { spec_index: 1, correspondent: null, document_type: null, tags: [], date_from: null, date_to: null },
      ],
      dropped: [
        { name: 'Acme', reason: 'none', candidates: [] },
      ],
    });
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('1 filter resolved');
    expect(container.textContent).toContain('1 dropped');
  });

  it('retrieve: shows chunk and doc counts', () => {
    const record = makeRetrieveRecord([
      { chunk_id: 1, document_id: 1, title: 'Doc A', snippet: 'abc', vector_similarity: 0.9 },
    ]);
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('1 chunk');
    expect(container.textContent).toContain('2 document');
  });

  it('gate: shows passed documents and best similarity', () => {
    const record = makeGateRecord([
      { document_id: 1, title: 'Doc A', best_similarity: 0.64 },
    ]);
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('Passed 1 document');
    expect(container.textContent).toContain('0.64');
  });

  it('judge: shows all-dropped summary when bailed', () => {
    const record: PhaseRecord = {
      phase: 'judge',
      label: 'Judging relevance',
      detail: { bailed: true, degraded: false, verdicts: [] },
      tokens: null, cost: null, ms: 1,
    };
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('No document judged relevant');
  });

  it('judge: shows kept/dropped counts', () => {
    const record: PhaseRecord = {
      phase: 'judge',
      label: 'Judging relevance',
      detail: {
        bailed: false,
        degraded: false,
        verdicts: [
          { doc_id: 1, title: 'A', keep: true, reason: 'yes', score: 0.8, paperless_url: null },
          { doc_id: 2, title: 'B', keep: false, reason: 'no', score: 0.1, paperless_url: null },
        ],
      },
      tokens: null, cost: null, ms: 1,
    };
    const { container } = render(<>{phaseSummary(record)}</>);
    expect(container.textContent).toContain('Kept 1');
    expect(container.textContent).toContain('dropped 1');
  });
});

describe('phaseToStages summary/body split', () => {
  it('plan: stage has summary and body', () => {
    const stage = phaseToStages([makePlanRecord(2)], null)[0]!;
    const { container: sc } = render(<>{stage.summary}</>);
    expect(sc.textContent).toContain('2 searches planned');
    expect(stage.body).toBeTruthy();
  });

  it('resolve: body shows "no filters proposed" for specs with no filters', () => {
    const record = makeResolveRecord({
      resolved: [
        { spec_index: 0, correspondent: null, document_type: null, tags: [], date_from: null, date_to: null },
      ],
      dropped: [],
    });
    const stage = phaseToStages([record], null)[0]!;
    const { container } = render(<>{stage.body}</>);
    expect(container.textContent).toContain('no filters proposed');
  });

  it('resolve: body shows resolved name and loosened tag when method=loose', () => {
    const record = makeResolveRecord({
      resolved: [
        {
          spec_index: 0,
          correspondent: null,
          document_type: { id: 12, name: 'Property Deed', method: 'loose' },
          tags: [],
          date_from: null,
          date_to: null,
        },
      ],
      dropped: [],
    });
    const stage = phaseToStages([record], null)[0]!;
    const { container } = render(<>{stage.body}</>);
    expect(container.textContent).toContain('Property Deed');
    expect(container.textContent).toContain('loosened');
  });

  it('resolve: body shows reason-aware dropped lines', () => {
    const record = makeResolveRecord({
      resolved: [],
      dropped: [
        { name: 'Acme', reason: 'none', candidates: [] },
        { name: 'Deed', reason: 'ambiguous', candidates: ['Property Deed', 'Trust Deed'] },
      ],
    });
    const stage = phaseToStages([record], null)[0]!;
    const { container } = render(<>{stage.body}</>);
    expect(container.textContent).toContain('Dropped (no match): Acme');
    expect(container.textContent).toContain('Dropped (ambiguous): Deed → Property Deed, Trust Deed');
  });

  it('retrieve: body lists chunks with title and snippet', () => {
    const record = makeRetrieveRecord([
      { chunk_id: 1, document_id: 1, title: 'Land Registry Deed', snippet: 'some snippet text', vector_similarity: 0.74 },
    ]);
    const stage = phaseToStages([record], null)[0]!;
    const { container } = render(<>{stage.body}</>);
    expect(container.textContent).toContain('Land Registry Deed');
    expect(container.textContent).toContain('some snippet text');
    expect(container.textContent).toContain('0.74');
  });

  it('gate: body lists documents with title and similarity bar', () => {
    const record = makeGateRecord([
      { document_id: 1, title: 'Property Deed Folio', best_similarity: 0.64 },
    ]);
    const stage = phaseToStages([record], null)[0]!;
    const { container } = render(<>{stage.body}</>);
    expect(container.textContent).toContain('Property Deed Folio');
    expect(container.textContent).toContain('0.64');
  });

  it('judge: body contains verdict list from verdictsOf', () => {
    const record: PhaseRecord = {
      phase: 'judge',
      label: 'Judging relevance',
      detail: {
        bailed: false,
        degraded: false,
        verdicts: [
          { doc_id: 1, title: 'Alpha Doc', keep: true, reason: 'relevant', score: 0.9, paperless_url: null },
        ],
      },
      tokens: null, cost: null, ms: 1,
    };
    const stage = phaseToStages([record], null)[0]!;
    // judge keeps its verdicts on the dedicated field; the body is left to
    // PipelineStages, which renders the verdict list (with the View control)
    // from `verdicts` so it does not duplicate with `body`.
    expect(stage.body == null).toBe(true);
    // verdicts still populated for back-compat
    expect(stage.verdicts).toBeDefined();
    expect(stage.verdicts!.length).toBe(1);
  });
});
