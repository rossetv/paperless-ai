import { render, screen } from '@testing-library/react';
import { LoadingScreen } from './LoadingScreen';

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

describe('LoadingScreen', () => {
  it('recaps the current query', () => {
    render(
      <LoadingScreen
        query="how much did I pay npower"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    expect(screen.getByDisplayValue('how much did I pay npower')).toBeInTheDocument();
  });

  it('renders the filter rail', () => {
    render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  it('announces that a search is running', () => {
    render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    expect(screen.getByText(/searching your library/i)).toBeInTheDocument();
  });

  it('renders the three pipeline stages', () => {
    render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    expect(screen.getByText(/planning the query/i)).toBeInTheDocument();
    expect(screen.getByText(/embedding & retrieving/i)).toBeInTheDocument();
    expect(screen.getByText(/synthesising the answer/i)).toBeInTheDocument();
  });

  it('marks the active stage as in progress', () => {
    render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it('renders the live elapsed counter', () => {
    render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    // Starts at 0s and ticks up — assert the seconds-counter format renders.
    expect(screen.getByText(/^\d+s$/)).toBeInTheDocument();
  });

  it('renders skeleton source placeholders', () => {
    const { container } = render(
      <LoadingScreen
        query="q"
        filters={EMPTY_FILTERS}
        onFiltersChange={() => {}}
      />,
    );
    // The Skeleton primitive renders aria-hidden placeholder spans.
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });
});
