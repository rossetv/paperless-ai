import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { SearchTracePanel } from './SearchTracePanel';
import type { CostSummary, PhaseRecord } from '../../../api/types';

const PHASES: PhaseRecord[] = [
  {
    phase: 'plan',
    label: 'Planning the query',
    detail: { rewritten_query: 'npower bills 2024', skipped_trivial: false },
    tokens: { prompt: 1200, completion: 40, reasoning: 0, total: 1240 },
    cost: { usd: 0.004, local: false },
    ms: 320,
  },
  {
    phase: 'judge',
    label: 'Judging relevance',
    detail: {
      degraded: false,
      bailed: false,
      verdicts: [
        {
          doc_id: 9823,
          title: 'Annual statement',
          keep: true,
          reason: 'matches',
          score: 0.91,
          paperless_url: 'http://paperless/documents/9823/',
        },
        {
          doc_id: 4410,
          title: 'Old letter',
          keep: false,
          reason: 'wrong year',
          score: 0.15,
          paperless_url: 'http://paperless/documents/4410/',
        },
      ],
    },
    tokens: { prompt: 800, completion: 60, reasoning: 0, total: 860 },
    cost: { usd: 0.002, local: false },
    ms: 540,
  },
];

const COST: CostSummary = {
  tokens: { prompt: 2000, completion: 100, reasoning: 0, total: 2100 },
  usd: 0.006,
  local: false,
  llm_calls: 2,
};

describe('SearchTracePanel', () => {
  it('renders the "How this answer was found" disclosure title', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    expect(screen.getByText(/how this answer was found/i)).toBeInTheDocument();
  });

  it('shows a tokens-only whole-query chip in the summary', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    // The header aggregate carries only the token count; the per-stage dollar
    // figures live on the individual rows (UI-16).
    expect(screen.getByText('2.1k tok')).toBeInTheDocument();
  });

  it('lists each phase when opened', async () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    await userEvent.click(screen.getByText(/how this answer was found/i));
    expect(screen.getByText('Planning the query')).toBeInTheDocument();
    expect(screen.getByText('Judging relevance')).toBeInTheDocument();
  });

  it('shows the per-phase cost chips', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    // The planner phase carries its own chip.
    expect(screen.getByText('1.2k tok · $0.004')).toBeInTheDocument();
  });

  it('shows the judge per-document rationales, scores and keep/drop tags', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    expect(screen.getByText('Annual statement')).toBeInTheDocument();
    expect(screen.getByText('matches')).toBeInTheDocument();
    expect(screen.getByText('Old letter')).toBeInTheDocument();
    expect(screen.getByText('wrong year')).toBeInTheDocument();
    // The judge score prefixes each verdict; keep/drop tags label the outcome.
    expect(screen.getByText('0.91')).toBeInTheDocument();
    expect(screen.getByText('0.15')).toBeInTheDocument();
    expect(screen.getByText('keep')).toBeInTheDocument();
    expect(screen.getByText('drop')).toBeInTheDocument();
  });

  it('starts collapsed', () => {
    const { container } = render(
      <SearchTracePanel phases={PHASES} cost={COST} />,
    );
    expect(container.querySelector('details')).not.toHaveAttribute('open');
  });

  it('renders without a cost chip when no cost summary is given (error path)', () => {
    render(<SearchTracePanel phases={PHASES} />);
    expect(screen.getByText(/how this answer was found/i)).toBeInTheDocument();
    expect(screen.queryByText(/2\.1k tok/)).not.toBeInTheDocument();
  });

  it('renders nothing when there are no phases', () => {
    const { container } = render(<SearchTracePanel phases={[]} cost={COST} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the planner per-spec searches, resolve, and refine details', () => {
    const phases: PhaseRecord[] = [
      {
        phase: 'plan',
        label: 'Planning the query',
        detail: {
          skipped_trivial: false,
          specs: [
            {
              mode: 'hybrid',
              query: 'npower energy 2024',
              filters: { correspondent: 'Npower', tags: [], date_from: null, date_to: null },
              rationale: 'find the annual spend',
            },
          ],
        },
        tokens: { prompt: 100, completion: 10, reasoning: 0, total: 110 },
        cost: { usd: 0.001, local: false },
        ms: 12,
      },
      {
        phase: 'resolve',
        label: 'Resolving filters',
        detail: {
          resolved: [
            {
              spec_index: 0,
              correspondent_id: 7,
              document_type_id: null,
              tag_ids: [],
              date_from: null,
              date_to: null,
            },
          ],
          dropped: [{ spec_index: 0, names: ['Mystery Co'] }],
        },
        tokens: null,
        cost: null,
        ms: 2,
      },
      {
        phase: 'refine',
        label: 'Refining',
        detail: {
          gap: 'no Q4 figure',
          action: 're-planned: 1 new searches',
          new_specs: [{ mode: 'semantic', query: 'Q4 invoice total' }],
          carried_over: 3,
          noop: false,
        },
        tokens: null,
        cost: null,
        ms: 3,
      },
    ];
    const { container } = render(<SearchTracePanel phases={phases} cost={COST} />);
    const text = container.textContent ?? '';
    // Plan body: query text and filter chips ("from " key + "Npower" value are
    // in separate spans, so we assert on container.textContent rather than
    // getByText, which requires a single matching element).
    expect(text).toContain('npower energy 2024');
    expect(text).toContain('from');
    expect(text).toContain('Npower');
    // The resolve body renders the legacy id wire as a "from" chip with the id
    // "#7" (no name on the legacy shape); the new object wire would show the
    // resolved name instead. The chip's label and value are separate spans, so
    // assert on each rather than the concatenation.
    expect(text).toContain('#7');
    // The legacy {spec_index, names} drop is grouped under its query and shown
    // as a struck chip with a "no match" reason, not a flat trailing line.
    expect(text).toContain('Mystery Co');
    expect(text).toContain('no match');
    // Refine body: short summary line + styled context lines + a styled query
    // block (matching the planning phase), not the old flat "New search 1:" dump.
    expect(text).toContain('1 search added');
    expect(text).toContain('no Q4 figure');
    expect(text).toContain('Q4 invoice total');
    expect(text).not.toContain('New search 1');
  });

  it('opens a judged document preview via the threaded onPreview handler', async () => {
    const onPreview = vi.fn();
    render(<SearchTracePanel phases={PHASES} cost={COST} onPreview={onPreview} />);
    const previews = screen.getAllByRole('button', { name: /view/i });
    expect(previews).toHaveLength(2);
    await userEvent.click(previews[0] as HTMLElement);
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('renders no View control when no onPreview handler is given', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    expect(
      screen.queryByRole('button', { name: /view/i }),
    ).not.toBeInTheDocument();
  });
});
