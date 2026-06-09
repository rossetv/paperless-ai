import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
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
        { doc_id: 9823, title: 'Annual statement', keep: true, reason: 'matches' },
        { doc_id: 4410, title: 'Old letter', keep: false, reason: 'wrong year' },
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

  it('shows the whole-query cost chip in the summary', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    expect(screen.getByText('2.1k tok · $0.006')).toBeInTheDocument();
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

  it('shows the judge per-document rationales', () => {
    render(<SearchTracePanel phases={PHASES} cost={COST} />);
    expect(screen.getByText('Annual statement')).toBeInTheDocument();
    expect(screen.getByText('matches')).toBeInTheDocument();
    expect(screen.getByText('Old letter')).toBeInTheDocument();
    expect(screen.getByText('wrong year')).toBeInTheDocument();
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
});
