import { render, screen } from '@testing-library/react';
import { LoadingScreen } from './LoadingScreen';
import type { PhaseRecord } from '../../../api/types';

// FilterControls drives useFacets; stub it out to stay off the facets API.
vi.mock('../../../components/patterns/FilterControls/FilterControls', () => ({
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
      {
        doc_id: 9823,
        title: 'Annual statement',
        keep: true,
        reason: 'on point',
        score: 0.95,
        paperless_url: 'http://paperless/documents/9823/',
      },
      {
        doc_id: 4410,
        title: 'Old letter',
        keep: false,
        reason: 'wrong year',
        score: 0.12,
        paperless_url: 'http://paperless/documents/4410/',
      },
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
    expect(screen.getByText(/^\d+:\d{2}$/)).toBeInTheDocument();
  });

  it('keeps the elapsed timer out of any live region', () => {
    const { container } = renderLoading({ activePhase: 'plan' });
    const timer = screen.getByText(/^\d+:\d{2}$/);
    expect(timer.closest('[role="status"], [aria-live]')).toBeNull();
    const live = container.querySelectorAll('[aria-live]');
    expect(live.length).toBeGreaterThan(0);
  });

  it('announces the running phase in a live region', () => {
    renderLoading({ activePhase: 'plan' });
    const live = screen
      .getAllByRole('status')
      .find((el) => el.getAttribute('aria-live') === 'polite');
    expect(live).toHaveTextContent(/planning the query/i);
  });

  it('renders skeleton source placeholders', () => {
    const { container } = renderLoading();
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });

  it('shows the active phase as in progress', () => {
    renderLoading({ phaseRecords: [], activePhase: 'plan' });
    expect(screen.getAllByText(/planning the query/i)).toHaveLength(2);
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it('renders the planner rewritten query from a completed phase', () => {
    renderLoading({ phaseRecords: [PLAN_RECORD], activePhase: 'retrieve' });
    expect(screen.getByText(/Rewritten:/)).toBeInTheDocument();
    expect(screen.getByText(/npower bills 2024/)).toBeInTheDocument();
    // With one phase the header's cumulative counter equals the phase chip.
    expect(
      screen.getAllByText('1.2k tok · $0.004').length,
    ).toBeGreaterThanOrEqual(1);
  });

  it('shows the judge summary line in the live rail (no verdict details)', () => {
    renderLoading({
      phaseRecords: [PLAN_RECORD, JUDGE_RECORD],
      activePhase: 'synthesise',
    });
    expect(screen.getByText(/planning the query/i)).toBeInTheDocument();
    expect(screen.getByText(/judging relevance/i)).toBeInTheDocument();
    // The live rail omits verdict details.
    expect(screen.queryByText('Annual statement')).toBeNull();
    expect(screen.queryByText('wrong year')).toBeNull();
    expect(screen.getAllByText(/synthesising the answer/i)).toHaveLength(2);
  });

  it('shows a cumulative token/cost total summed across phase records', () => {
    const record1: PhaseRecord = {
      phase: 'plan',
      label: 'Planning the query',
      detail: { skipped_trivial: false, specs: [] },
      tokens: { prompt: 2900, completion: 200, reasoning: 0, total: 3100 },
      cost: { usd: 0.0091, local: false },
      ms: 1,
    };
    const record2: PhaseRecord = {
      phase: 'judge',
      label: 'Judging relevance',
      detail: { bailed: true, degraded: false, verdicts: [] },
      tokens: { prompt: 2400, completion: 200, reasoning: 0, total: 2600 },
      cost: { usd: 0.005, local: false },
      ms: 1,
    };
    renderLoading({
      phaseRecords: [record1, record2],
      activePhase: null,
    });
    // 3100 + 2600 = 5700 → "5.7k tok"; 0.0091 + 0.0050 = 0.0141 → "$0.0141"
    expect(screen.getByText(/5\.7k tok · \$0\.014/)).toBeInTheDocument();
  });

  it('does not render the cost counter when total tokens is zero', () => {
    renderLoading({
      phaseRecords: [],
      activePhase: null,
    });
    expect(screen.queryByText(/tok ·/)).toBeNull();
  });

  it('renders no rail before any phase has started', () => {
    const { container } = renderLoading({
      phaseRecords: [],
      activePhase: null,
    });
    expect(container.querySelector('ol')).not.toBeInTheDocument();
  });
});
