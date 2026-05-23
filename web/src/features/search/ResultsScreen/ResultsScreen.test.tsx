import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SearchResponse } from '../../../api/types';
import { ResultsScreen } from './ResultsScreen';

vi.mock('../FilterControls/FilterControls', () => ({
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
  answer: 'You paid £1,847.32 to Npower in 2024 [1].',
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
      tags: [],
    },
  ],
  plan: {
    semantic_queries: ['Annual energy payments to Npower in 2024'],
    keyword_terms: ['Npower', '2024'],
    sub_questions: [],
  },
  stats: { llm_calls: 3, latency_ms: 1842, refined: true },
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

  it('renders the query-plan disclosure', () => {
    renderResults();
    expect(screen.getByText(/how this answer was built/i)).toBeInTheDocument();
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

  it('fires onPreview when a source preview is clicked', async () => {
    const onPreview = vi.fn();
    renderResults({ onPreview });
    await userEvent.click(
      screen.getByRole('button', { name: /^preview$/i }),
    );
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('highlights the cited source when highlightedIndex is set', () => {
    const { container } = renderResults({ highlightedIndex: 1 });
    // The SourceCardSurface applies a `highlighted` modifier class.
    expect(container.innerHTML).toMatch(/highlighted/);
  });
});
