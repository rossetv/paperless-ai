import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ApiError, Unauthenticated } from '../api/client';
import { SearchPage } from './SearchPage';

// AppNavBar drives useAuth/useLogout + router; mock it to a plain div.
vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => React.createElement('div', { 'data-testid': 'mock-navbar' }),
}));

// The screen features are exercised in their own suites; here, mock each to a
// tiny probe so the page-orchestration logic is tested in isolation.
vi.mock('../features/search/IdleScreen/IdleScreen', () => ({
  IdleScreen: ({ onSearch }: { onSearch: (q: string) => void }) =>
    React.createElement(
      'button',
      { 'data-testid': 'idle', onClick: () => onSearch('npower bills') },
      'idle',
    ),
}));
vi.mock('../features/search/LoadingScreen/LoadingScreen', () => ({
  LoadingScreen: () =>
    React.createElement('div', { 'data-testid': 'loading' }),
}));
vi.mock('../features/search/ResultsScreen/ResultsScreen', () => ({
  ResultsScreen: ({
    query,
    onPreview,
    onSearch,
  }: {
    query: string;
    onPreview: (id: number) => void;
    onSearch: (q: string) => void;
  }) =>
    React.createElement(
      'div',
      { 'data-testid': 'results' },
      React.createElement('span', { 'data-testid': 'results-query' }, query),
      React.createElement(
        'button',
        { 'data-testid': 'results-preview', onClick: () => onPreview(9823) },
        'preview',
      ),
      React.createElement(
        'button',
        {
          'data-testid': 'results-new-search',
          onClick: () => onSearch('rolling-blackout refunds'),
        },
        'new search',
      ),
    ),
}));
vi.mock('../features/search/NoResultsScreen/NoResultsScreen', () => ({
  NoResultsScreen: ({ onSearch }: { onSearch: (q: string) => void }) =>
    React.createElement(
      'button',
      {
        'data-testid': 'no-results',
        onClick: () => onSearch('octopus tariff'),
      },
      'no-results',
    ),
}));
vi.mock('../features/search/IndexNotReadyScreen/IndexNotReadyScreen', () => ({
  IndexNotReadyScreen: () =>
    React.createElement('div', { 'data-testid': 'index-not-ready' }),
}));
vi.mock('../features/search/SearchErrorScreen/SearchErrorScreen', () => ({
  SearchErrorScreen: ({ onSearch }: { onSearch: (q: string) => void }) =>
    React.createElement(
      'button',
      {
        'data-testid': 'search-error',
        onClick: () => onSearch('boiler service'),
      },
      'search-error',
    ),
}));

vi.mock('../api/hooks', () => ({
  useSearch: vi.fn(),
  ME_QUERY_KEY: ['auth', 'me'],
}));

import { useSearch } from '../api/hooks';
const mockUseSearch = useSearch as ReturnType<typeof vi.fn>;

/** Build a useSearch result stub in the requested state. */
function searchResult(overrides: Record<string, unknown>) {
  return {
    data: undefined,
    error: null,
    isPending: false,
    isFetching: false,
    isError: false,
    isSuccess: false,
    refetch: vi.fn(),
    ...overrides,
  };
}

const SUCCESS_DATA = {
  answer: 'An answer [1].',
  sources: [
    {
      document_id: 9823,
      title: 'A document',
      correspondent: 'Npower',
      document_type: 'Statement',
      created: '2025-01-12',
      snippet: 'snippet',
      paperless_url: 'https://paperless.example.com/documents/9823/',
      score: 0.9,
      tags: ['Utilities'],
    },
  ],
  plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
  stats: { llm_calls: 1, latency_ms: 100, refined: false },
};

/**
 * Records the current location for assertion — rendered inside the router so
 * it can access the location context.
 */
function LocationProbe({
  locationRef,
}: {
  locationRef: React.MutableRefObject<string>;
}) {
  const location = useLocation();
  locationRef.current = location.pathname + location.search;
  return null;
}

function renderPage(initialUrl = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const locationRef = React.createRef() as React.MutableRefObject<string>;
  locationRef.current = initialUrl;

  return {
    queryClient,
    locationRef,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialUrl]}>
          <LocationProbe locationRef={locationRef} />
          <Routes>
            <Route path="/" element={<SearchPage />} />
            <Route path="/document/:id" element={<div data-testid="document-preview-route" />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

describe('SearchPage', () => {
  it('renders the IdleScreen when there is no query', () => {
    mockUseSearch.mockReturnValue(searchResult({ isPending: true }));
    renderPage();
    expect(screen.getByTestId('idle')).toBeInTheDocument();
  });

  it('renders the LoadingScreen while a search is in flight', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isPending: false, isFetching: true }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('loading')).toBeInTheDocument();
  });

  it('renders the ResultsScreen on a successful search with sources', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('results')).toBeInTheDocument();
  });

  it('renders the NoResultsScreen when a search returns zero sources', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({
        isSuccess: true,
        data: { ...SUCCESS_DATA, sources: [] },
      }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('no-results')).toBeInTheDocument();
  });

  it('renders the IndexNotReadyScreen on a 503 search error', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isError: true, error: new ApiError(503) }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('index-not-ready')).toBeInTheDocument();
  });

  it('renders the SearchErrorScreen on a generic search error', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isError: true, error: new ApiError(500) }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('search-error')).toBeInTheDocument();
  });

  it('invalidates the me query when a search returns Unauthenticated', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isError: true, error: new Unauthenticated() }),
    );
    const { queryClient } = renderPage();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    await userEvent.click(screen.getByTestId('idle'));
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['auth', 'me'],
      });
    });
  });

  it('runs a second, different search from the results view', async () => {
    // Regression: once a search ran, `query` never reset and only the idle
    // screen had an editable field — the user was stranded on the results
    // screen with no way to start a fresh search short of a full reload.
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    renderPage();

    // First search — from the idle hero.
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('results-query')).toHaveTextContent(
      'npower bills',
    );

    // Second search — from the editable recap field on the results screen.
    await userEvent.click(screen.getByTestId('results-new-search'));

    // The page re-runs the search with the NEW query, no reload needed.
    expect(screen.getByTestId('results-query')).toHaveTextContent(
      'rolling-blackout refunds',
    );
    expect(mockUseSearch).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'rolling-blackout refunds' }),
    );
  });

  it('mounting at /?q=invoice triggers the search', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    renderPage('/?q=invoice');
    // The results screen renders immediately — no interaction needed.
    await waitFor(() => {
      expect(screen.getByTestId('results')).toBeInTheDocument();
    });
    expect(mockUseSearch).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'invoice' }),
    );
  });

  it('mounting at / shows the IdleScreen', () => {
    mockUseSearch.mockReturnValue(searchResult({ isPending: true }));
    renderPage('/');
    expect(screen.getByTestId('idle')).toBeInTheDocument();
  });

  it('submitting a search from / updates the URL to /?q=…', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isPending: false, isFetching: true }),
    );
    const { locationRef } = renderPage('/');
    await userEvent.click(screen.getByTestId('idle'));
    await waitFor(() => {
      expect(locationRef.current).toBe('/?q=npower+bills');
    });
  });

  it('opening a preview navigates to /document/<id> with the search context preserved', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    const { locationRef } = renderPage('/?q=invoice');
    await waitFor(() => {
      expect(screen.getByTestId('results')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByTestId('results-preview'));
    await waitFor(() => {
      expect(locationRef.current).toBe('/document/9823?q=invoice');
    });
  });
});
