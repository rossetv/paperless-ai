import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SearchResponse } from '../../../api/types';
import { ResultsScreen } from './ResultsScreen';

vi.mock('../../../components/patterns/FilterControls/FilterControls', () => ({
  FilterControls: () => <div data-testid="mock-filter-controls" />,
}));

// ActiveFiltersStrip calls useFacets — mock it so the test has no query client.
vi.mock('../ActiveFiltersStrip/ActiveFiltersStrip', () => ({
  ActiveFiltersStrip: () => null,
}));

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

const RESPONSE: SearchResponse = {
  // Citation marker uses the document_id of the source, matching the
  // synthesiser's real output format. The AnswerCard resolves [9823] to the
  // source's 1-based position (1) for display.
  answer: 'You paid £1,847.32 to Npower in 2024 [9823].',
  sources: [
    {
      document_id: 9823,
      title: 'Annual energy statement',
      correspondent: 'Npower Energy',
      document_type: 'Statement',
      created: '2025-01-12',
      snippet: 'Total charges were **£1,847.32**.',
      paperless_url: 'https://paperless.example.com/documents/9823/',
      score: 0.92,
      relevance_tier: 'strong',
      tags: [],
    },
  ],
  plan: { specs: [] },
  stats: { llm_calls: 3, latency_ms: 1842, refined: true },
  trace: {
    phases: [
      {
        phase: 'plan',
        label: 'Planning the query',
        detail: { rewritten_query: 'Npower 2024 payments', skipped_trivial: false },
        tokens: { prompt: 1100, completion: 40, reasoning: 0, total: 1140 },
        cost: { usd: 0.004, local: false },
        ms: 300,
      },
    ],
  },
  cost: {
    tokens: { prompt: 2000, completion: 100, reasoning: 0, total: 2100 },
    usd: 0.006,
    local: false,
    llm_calls: 3,
  },
  outcome_kind: 'answered',
};

function renderResults(overrides = {}) {
  return render(
    <ResultsScreen
      query="how much did I pay npower in 2024"
      filters={EMPTY_FILTERS}
      result={RESPONSE}
      docCount={RESPONSE.sources.length}
      onFiltersChange={() => {}}
      onSearch={() => {}}
      onClearFilters={() => {}}
      onCitationActivate={() => {}}
      onPreview={() => {}}
      {...overrides}
    />,
  );
}

describe('ResultsScreen', () => {
  it('recaps the query', () => {
    renderResults();
    expect(
      screen.getByDisplayValue('how much did I pay npower in 2024'),
    ).toBeInTheDocument();
  });

  it('runs a fresh search when the editable recap field is submitted', async () => {
    const onSearch = vi.fn();
    renderResults({ onSearch });
    const recap = screen.getByDisplayValue(
      'how much did I pay npower in 2024',
    );
    await userEvent.clear(recap);
    await userEvent.type(recap, 'octopus tariff for 2025{Enter}');
    expect(onSearch).toHaveBeenCalledWith('octopus tariff for 2025');
  });

  it('renders the filter rail', () => {
    renderResults();
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  it('renders the synthesised answer', () => {
    renderResults();
    expect(screen.getByText(/you paid £1,847.32 to npower/i)).toBeInTheDocument();
  });

  it('renders a "Sources" header', () => {
    renderResults();
    expect(
      screen.getByRole('heading', { name: /sources/i }),
    ).toBeInTheDocument();
  });

  it('renders the Sources caption', () => {
    renderResults();
    expect(
      screen.getByText(/the documents that grounded the answer above/i),
    ).toBeInTheDocument();
  });

  it('renders the source card', () => {
    renderResults();
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
  });

  it('renders the reasoning-trace disclosure', () => {
    renderResults();
    expect(screen.getByText(/how this answer was found/i)).toBeInTheDocument();
  });

  it('renders the whole-query cost chip', () => {
    renderResults();
    // The same whole-query tokens · cost appears in both the answer footer and
    // the trace-panel summary — assert at least one is present.
    expect(screen.getAllByText('2.1k tok · $0.006').length).toBeGreaterThan(0);
  });

  it('fires onCitationActivate when a citation is clicked', async () => {
    const onCitationActivate = vi.fn();
    renderResults({ onCitationActivate });
    await userEvent.click(
      screen.getByRole('button', { name: /view source 1/i }),
    );
    expect(onCitationActivate).toHaveBeenCalledWith(1);
  });

  it('fires onPreview with the source document_id when a citation is clicked', async () => {
    const onPreview = vi.fn();
    renderResults({ onPreview });
    await userEvent.click(
      screen.getByRole('button', { name: /view source 1/i }),
    );
    // RESPONSE.sources[0].document_id === 9823
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('fires both onCitationActivate and onPreview when a citation is clicked', async () => {
    const onCitationActivate = vi.fn();
    const onPreview = vi.fn();
    renderResults({ onCitationActivate, onPreview });
    await userEvent.click(
      screen.getByRole('button', { name: /view source 1/i }),
    );
    expect(onCitationActivate).toHaveBeenCalledWith(1);
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('fires onPreview when a source view is clicked', async () => {
    const onPreview = vi.fn();
    renderResults({ onPreview });
    await userEvent.click(
      screen.getByRole('button', { name: /^view$/i }),
    );
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('highlights the cited source when highlightedIndex is set', () => {
    const { container } = renderResults({ highlightedIndex: 1 });
    // The SourceCardSurface applies a `highlighted` modifier class.
    expect(container.innerHTML).toMatch(/highlighted/);
  });
});
