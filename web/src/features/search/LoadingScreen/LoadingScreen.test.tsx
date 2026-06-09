import { render, screen } from '@testing-library/react';
import { LoadingScreen } from './LoadingScreen';
import type { PhaseRecord } from '../../../api/types';

// FilterControls drives useFacets; mock it to a static element so the
// LoadingScreen test stays isolated from the facets API.
vi.mock('../FilterControls/FilterControls', () => ({
  FilterControls: () => <div data-testid="mock-filter-controls" />,
}));

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

/** A completed planner phase carrying a rewritten query and a cost. */
const PLAN_RECORD: PhaseRecord = {
  phase: 'plan',
  label: 'Planning the query',
  detail: { rewritten_query: 'npower bills 2024', skipped_trivial: false },
  tokens: { prompt: 1200, completion: 40, reasoning: 0, total: 1240 },
  cost: { usd: 0.004, local: false },
  ms: 320,
};

/** A completed judge phase that dropped one document. */
const JUDGE_RECORD: PhaseRecord = {
  phase: 'judge',
  label: 'Judging relevance',
  detail: {
    degraded: false,
    bailed: false,
    verdicts: [
      { doc_id: 9823, title: 'Annual statement', keep: true, reason: 'on point' },
      { doc_id: 4410, title: 'Old letter', keep: false, reason: 'wrong year' },
    ],
  },
  tokens: { prompt: 800, completion: 60, reasoning: 0, total: 860 },
  cost: { usd: 0.002, local: false },
  ms: 540,
};

function renderLoading(
  overrides: Partial<React.ComponentProps<typeof LoadingScreen>> = {},
) {
  return render(
    <LoadingScreen
      query="how much did I pay npower"
      filters={EMPTY_FILTERS}
      onFiltersChange={() => {}}
      phaseRecords={[]}
      activePhase={null}
      {...overrides}
    />,
  );
}

describe('LoadingScreen', () => {
  it('recaps the current query', () => {
    renderLoading();
    expect(
      screen.getByDisplayValue('how much did I pay npower'),
    ).toBeInTheDocument();
  });

  it('renders the filter rail', () => {
    renderLoading();
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  it('announces that a search is running', () => {
    renderLoading();
    expect(screen.getByText(/searching your library/i)).toBeInTheDocument();
  });

  it('renders the live elapsed counter', () => {
    renderLoading();
    // Starts at 0s and ticks up — assert the seconds-counter format renders.
    expect(screen.getByText(/^\d+s$/)).toBeInTheDocument();
  });

  it('renders skeleton source placeholders', () => {
    const { container } = renderLoading();
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });

  it('shows the active phase as in progress', () => {
    renderLoading({ phaseRecords: [], activePhase: 'plan' });
    expect(screen.getByText(/planning the query/i)).toBeInTheDocument();
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it('renders the planner rewritten query from a completed phase', () => {
    renderLoading({ phaseRecords: [PLAN_RECORD], activePhase: 'retrieve' });
    expect(screen.getByText(/Rewritten:/)).toBeInTheDocument();
    expect(screen.getByText(/npower bills 2024/)).toBeInTheDocument();
    // The LLM phase carries a token/cost chip.
    expect(screen.getByText('1.2k tok · $0.004')).toBeInTheDocument();
  });

  it('renders the judge kept/dropped verdicts', () => {
    renderLoading({
      phaseRecords: [PLAN_RECORD, JUDGE_RECORD],
      activePhase: 'synthesise',
    });
    expect(screen.getByText('Annual statement')).toBeInTheDocument();
    expect(screen.getByText('Old letter')).toBeInTheDocument();
    expect(screen.getByText('wrong year')).toBeInTheDocument();
    expect(screen.getByText('kept')).toBeInTheDocument();
    expect(screen.getByText('dropped')).toBeInTheDocument();
    // The synthesise phase is the active row.
    expect(screen.getByText(/synthesising the answer/i)).toBeInTheDocument();
  });

  it('renders no rail before any phase has started', () => {
    const { container } = renderLoading({ phaseRecords: [], activePhase: null });
    // No stages → no ordered list rendered inside the progress card.
    expect(container.querySelector('ol')).not.toBeInTheDocument();
  });
});
