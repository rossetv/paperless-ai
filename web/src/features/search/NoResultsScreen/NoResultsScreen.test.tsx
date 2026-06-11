import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { NoResultsScreen } from './NoResultsScreen';
import type { FilterRequest, SearchResponse } from '../../../api/types';

vi.mock('../FilterControls/FilterControls', () => ({
  FilterControls: () => <div data-testid="mock-filter-controls" />,
}));

// ActiveFiltersStrip calls useFacets — mock it so the test has no query client.
vi.mock('../ActiveFiltersStrip/ActiveFiltersStrip', () => ({
  ActiveFiltersStrip: () => null,
}));

// SearchTracePanel uses Disclosure — mock to a simple probe.
vi.mock('../SearchTracePanel/SearchTracePanel', () => ({
  SearchTracePanel: ({ phases }: { phases: unknown[] }) =>
    phases.length > 0 ? (
      <div data-testid="mock-trace-panel">How this answer was found</div>
    ) : null,
}));

const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

const ACTIVE_FILTERS: FilterRequest = {
  tag_ids: [1],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

const BASE_RESULT: SearchResponse = {
  answer: "I couldn't find any documents matching that.",
  sources: [],
  plan: { specs: [] },
  stats: { llm_calls: 1, latency_ms: 100, refined: false },
  trace: {
    phases: [
      { phase: 'plan', label: 'Planning', detail: {}, tokens: null, cost: null, ms: 1 },
    ],
  },
  cost: {
    tokens: { prompt: 0, completion: 0, reasoning: 0, total: 0 },
    usd: 0,
    local: false,
    llm_calls: 1,
  },
  outcome_kind: 'no_match',
  no_match_reason: 'empty_retrieval',
  candidate_count: null,
};

function renderScreen(
  resultOverrides: Partial<SearchResponse> = {},
  filters = EMPTY_FILTERS,
  props: Partial<{ onSearch: (q: string) => void; onClearFilters: () => void; onSearchWithoutFilters: () => void }> = {},
) {
  const result = { ...BASE_RESULT, ...resultOverrides };
  return render(
    <NoResultsScreen
      result={result}
      query="payslip from 2019 with a bonus over £4000"
      filters={filters}
      onFiltersChange={() => {}}
      onSearch={props.onSearch ?? (() => {})}
      onClearFilters={props.onClearFilters ?? (() => {})}
      onSearchWithoutFilters={props.onSearchWithoutFilters ?? (() => {})}
      onPreview={() => {}}
    />,
  );
}

describe('NoResultsScreen', () => {
  // ── recap field ─────────────────────────────────────────────────────────────

  it('recaps the query in the search field', () => {
    renderScreen();
    expect(
      screen.getByDisplayValue('payslip from 2019 with a bonus over £4000'),
    ).toBeInTheDocument();
  });

  it('runs a fresh search when the editable recap field is submitted', async () => {
    const onSearch = vi.fn();
    renderScreen({}, EMPTY_FILTERS, { onSearch });
    const recap = screen.getByDisplayValue(
      'payslip from 2019 with a bonus over £4000',
    );
    await userEvent.clear(recap);
    await userEvent.type(recap, '2020 payslips{Enter}');
    expect(onSearch).toHaveBeenCalledWith('2020 payslips');
  });

  it('renders the filter rail', () => {
    renderScreen();
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  // ── clarify ─────────────────────────────────────────────────────────────────

  it('clarify — shows the planner clarify text and a narrowing-down caption', () => {
    renderScreen({
      outcome_kind: 'clarify',
      answer: 'Which year and correspondent are you interested in?',
      no_match_reason: null,
    });
    expect(
      screen.getByText('Which year and correspondent are you interested in?'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/narrow things down/i),
    ).toBeInTheDocument();
  });

  it('clarify — does NOT render filter action buttons', () => {
    renderScreen({
      outcome_kind: 'clarify',
      answer: 'Which year?',
      no_match_reason: null,
    });
    expect(screen.queryByRole('button', { name: /clear filters/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /search without filters/i })).not.toBeInTheDocument();
  });

  // ── no_match / judge_rejected ────────────────────────────────────────────────

  it('judge_rejected — shows candidate count in the message', () => {
    renderScreen({
      outcome_kind: 'no_match',
      no_match_reason: 'judge_rejected',
      candidate_count: 7,
    });
    expect(screen.getByText(/I found 7 documents, but none matched/i)).toBeInTheDocument();
  });

  it('judge_rejected — falls back to "some documents" when count is null', () => {
    renderScreen({
      outcome_kind: 'no_match',
      no_match_reason: 'judge_rejected',
      candidate_count: null,
    });
    expect(screen.getByText(/I found some documents, but none matched/i)).toBeInTheDocument();
  });

  it('judge_rejected — shows filter action buttons when filters are set', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'judge_rejected', candidate_count: 3 },
      ACTIVE_FILTERS,
    );
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /search without filters/i })).toBeInTheDocument();
  });

  it('judge_rejected — hides filter action buttons when no filters are set', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'judge_rejected', candidate_count: 3 },
      EMPTY_FILTERS,
    );
    expect(screen.queryByRole('button', { name: /clear filters/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /search without filters/i })).not.toBeInTheDocument();
  });

  // ── no_match / empty_retrieval ───────────────────────────────────────────────

  it('empty_retrieval + filters set — shows filter-narrowed message and actions', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'empty_retrieval' },
      ACTIVE_FILTERS,
    );
    expect(
      screen.getByText(/your filters narrowed the search to zero results/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /search without filters/i })).toBeInTheDocument();
  });

  it('empty_retrieval + no filters — shows library message and no filter actions', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'empty_retrieval' },
      EMPTY_FILTERS,
    );
    expect(
      screen.getByText(/nothing in your library matched that search/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /clear filters/i })).not.toBeInTheDocument();
  });

  // ── no_match / weak_relevance ────────────────────────────────────────────────

  it('weak_relevance — shows rephrasing message', () => {
    renderScreen({ outcome_kind: 'no_match', no_match_reason: 'weak_relevance' });
    expect(
      screen.getByText(/closest matches weren't relevant enough/i),
    ).toBeInTheDocument();
  });

  it('weak_relevance + filters set — shows filter action buttons', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'weak_relevance' },
      ACTIVE_FILTERS,
    );
    expect(screen.getByRole('button', { name: /clear filters/i })).toBeInTheDocument();
  });

  it('weak_relevance + no filters — hides filter action buttons', () => {
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'weak_relevance' },
      EMPTY_FILTERS,
    );
    expect(screen.queryByRole('button', { name: /clear filters/i })).not.toBeInTheDocument();
  });

  // ── trace panel ─────────────────────────────────────────────────────────────

  it('renders the trace panel for a no_match result with phases', () => {
    renderScreen({
      outcome_kind: 'no_match',
      no_match_reason: 'empty_retrieval',
    });
    expect(screen.getByTestId('mock-trace-panel')).toBeInTheDocument();
    expect(screen.getByText(/how this answer was found/i)).toBeInTheDocument();
  });

  it('renders the trace panel for a clarify result with phases', () => {
    renderScreen({
      outcome_kind: 'clarify',
      answer: 'Too vague.',
      no_match_reason: null,
    });
    expect(screen.getByTestId('mock-trace-panel')).toBeInTheDocument();
  });

  it('does not render the trace panel when phases is empty', () => {
    renderScreen({
      outcome_kind: 'no_match',
      no_match_reason: 'empty_retrieval',
      trace: { phases: [] },
    });
    expect(screen.queryByTestId('mock-trace-panel')).not.toBeInTheDocument();
  });

  // ── "Try instead" suggestions ────────────────────────────────────────────────

  it('renders a "Try instead" heading', () => {
    renderScreen();
    expect(screen.getByText(/try instead/i)).toBeInTheDocument();
  });

  it('renders suggestion rows from QUICK_FILTERS', () => {
    renderScreen();
    expect(screen.getByRole('button', { name: /invoices this month/i })).toBeInTheDocument();
  });

  it('fires onSearch with the suggestion when a "Try instead" row is clicked', async () => {
    const onSearch = vi.fn();
    renderScreen({}, EMPTY_FILTERS, { onSearch });
    await userEvent.click(
      screen.getByRole('button', { name: /invoices this month/i }),
    );
    expect(onSearch).toHaveBeenCalledWith('Invoices this month');
  });

  // ── callback wiring ──────────────────────────────────────────────────────────

  it('fires onClearFilters when "Clear filters" is clicked', async () => {
    const onClearFilters = vi.fn();
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'empty_retrieval' },
      ACTIVE_FILTERS,
      { onClearFilters },
    );
    await userEvent.click(
      screen.getByRole('button', { name: /clear filters/i }),
    );
    expect(onClearFilters).toHaveBeenCalledTimes(1);
  });

  it('fires onSearchWithoutFilters when "Search without filters" is clicked', async () => {
    const onSearchWithoutFilters = vi.fn();
    renderScreen(
      { outcome_kind: 'no_match', no_match_reason: 'empty_retrieval' },
      ACTIVE_FILTERS,
      { onSearchWithoutFilters },
    );
    await userEvent.click(
      screen.getByRole('button', { name: /search without filters/i }),
    );
    expect(onSearchWithoutFilters).toHaveBeenCalledTimes(1);
  });
});
