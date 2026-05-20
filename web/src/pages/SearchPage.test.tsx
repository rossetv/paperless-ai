/**
 * Tests for SearchPage.
 *
 * Verifies that:
 * - an idle page renders the search bar with no results
 * - a search renders the answer and sources once the query resolves
 * - the empty state shows when a search returns no results
 * - the initialising state shows when a search returns 503 index-not-ready
 * - an Unauthenticated error from a search call triggers useAuth().logout()
 * - citation activation in AnswerCard highlights the matching source in SourceList
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import type { SearchResponse, FacetsResponse } from '../api/types';
import { Unauthenticated, ApiError } from '../api/client';
import { AuthProvider, useAuth } from '../hooks/useAuth';
import { SearchPage } from './SearchPage';

// ---------------------------------------------------------------------------
// Mock the feature components so the page layer is isolated
// ---------------------------------------------------------------------------

vi.mock('../features/search/SearchBar/SearchBar', () => ({
  SearchBar: ({ onSearch }: { onSearch: (q: string) => void }) =>
    React.createElement('button', {
      onClick: () => onSearch('test query'),
      'data-testid': 'mock-search-bar',
    }, 'Search'),
}));

vi.mock('../features/search/FilterControls/FilterControls', () => ({
  FilterControls: () => React.createElement('div', { 'data-testid': 'mock-filter-controls' }),
}));

vi.mock('../features/search/AnswerCard/AnswerCard', () => ({
  AnswerCard: ({
    answer,
    onCitationActivate,
  }: {
    answer: string;
    onCitationActivate?: (n: number) => void;
  }) =>
    React.createElement(
      'div',
      { 'data-testid': 'mock-answer-card' },
      answer,
      React.createElement('button', {
        onClick: () => onCitationActivate?.(1),
        'data-testid': 'mock-citation-btn',
      }, 'Activate [1]'),
    ),
}));

vi.mock('../features/search/SourceList/SourceList', () => ({
  SourceList: ({
    sources,
    highlightedIndex,
  }: {
    sources: { document_id: number; title: string | null }[];
    highlightedIndex?: number;
  }) =>
    React.createElement(
      'div',
      { 'data-testid': 'mock-source-list' },
      `sources:${sources.length} highlighted:${highlightedIndex ?? 'none'}`,
    ),
}));

vi.mock('../features/search/QueryPlanSummary/QueryPlanSummary', () => ({
  QueryPlanSummary: () =>
    React.createElement('div', { 'data-testid': 'mock-query-plan-summary' }),
}));

// ---------------------------------------------------------------------------
// Mock API hooks
// ---------------------------------------------------------------------------

vi.mock('../api/hooks', () => ({
  useSearch: vi.fn(),
  useFacets: vi.fn(),
  useLogin: vi.fn(),
}));

import { useSearch, useFacets } from '../api/hooks';
const mockUseSearch = useSearch as ReturnType<typeof vi.fn>;
const mockUseFacets = useFacets as ReturnType<typeof vi.fn>;

function makeFacetsResult(): UseQueryResult<FacetsResponse, Error> {
  return {
    data: {
      correspondents: [],
      document_types: [],
      tags: [],
      earliest: null,
      latest: null,
    },
    isLoading: false,
    isError: false,
    error: null,
    status: 'success',
    isSuccess: true,
    isPending: false,
    isFetching: false,
    isRefetching: false,
    isLoadingError: false,
    isRefetchError: false,
    isPlaceholderData: false,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    fetchStatus: 'idle',
    isPaused: false,
    isStale: false,
    isInitialLoading: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<FacetsResponse, Error>;
}

function makeSearchResult(
  overrides: Partial<UseQueryResult<SearchResponse, Error>>,
): UseQueryResult<SearchResponse, Error> {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    error: null,
    status: 'pending',
    isSuccess: false,
    isPending: true,
    isFetching: false,
    isRefetching: false,
    isLoadingError: false,
    isRefetchError: false,
    isPlaceholderData: false,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    fetchStatus: 'idle',
    isPaused: false,
    isStale: false,
    isInitialLoading: false,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as UseQueryResult<SearchResponse, Error>;
}

const successResponse: SearchResponse = {
  answer: 'The boiler was installed in 2021 [1].',
  sources: [
    {
      document_id: 1,
      title: 'Boiler contract',
      correspondent: 'Company Ltd',
      document_type: 'Contract',
      created: '2021-01-01',
      snippet: 'boiler installation',
      paperless_url: 'https://paperless.example.com/documents/1/',
      score: 0.95,
    },
  ],
  plan: { semantic_queries: ['boiler'], keyword_terms: [], sub_questions: [] },
  stats: { llm_calls: 2, latency_ms: 500, refined: false },
};

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderSearchPage(authLoggedIn = true) {
  mockUseFacets.mockReturnValue(makeFacetsResult());
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(
        MemoryRouter,
        null,
        React.createElement(
          AuthProvider,
          null,
          React.createElement(AuthInitialiser, { loggedIn: authLoggedIn, children }),
        ),
      ),
    );
  }

  return render(React.createElement(SearchPage), { wrapper: Wrapper });
}

/** Sets auth state before children render. */
function AuthInitialiser({
  loggedIn,
  children,
}: {
  loggedIn: boolean;
  children: React.ReactNode;
}): React.ReactElement {
  const auth = useAuth();
  React.useEffect(() => {
    if (loggedIn) auth.login();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return React.createElement(React.Fragment, null, children);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SearchPage', () => {
  beforeEach(() => {
    // By default, search is idle (empty query — hook disabled)
    mockUseSearch.mockReturnValue(
      makeSearchResult({ status: 'pending', isPending: true, data: undefined }),
    );
  });

  it('renders the search bar in the idle state', () => {
    renderSearchPage();
    expect(screen.getByTestId('mock-search-bar')).toBeInTheDocument();
  });

  it('renders filter controls', () => {
    renderSearchPage();
    expect(screen.getByTestId('mock-filter-controls')).toBeInTheDocument();
  });

  it('shows a loading indicator while a search is in flight', async () => {
    mockUseSearch.mockReturnValue(
      makeSearchResult({ status: 'pending', isPending: true, isFetching: true }),
    );
    renderSearchPage();
    await userEvent.click(screen.getByTestId('mock-search-bar'));
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders the answer card and source list when a search succeeds', async () => {
    mockUseSearch.mockReturnValue(
      makeSearchResult({
        status: 'success',
        isSuccess: true,
        isPending: false,
        data: successResponse,
      }),
    );
    renderSearchPage();
    await userEvent.click(screen.getByTestId('mock-search-bar'));

    await waitFor(() => {
      expect(screen.getByTestId('mock-answer-card')).toBeInTheDocument();
    });
    expect(screen.getByTestId('mock-source-list')).toBeInTheDocument();
    expect(screen.getByTestId('mock-query-plan-summary')).toBeInTheDocument();
  });

  it('shows the empty state when a search returns no results', async () => {
    mockUseSearch.mockReturnValue(
      makeSearchResult({
        status: 'success',
        isSuccess: true,
        isPending: false,
        data: { ...successResponse, answer: '', sources: [] },
      }),
    );
    renderSearchPage();
    await userEvent.click(screen.getByTestId('mock-search-bar'));

    await waitFor(() => {
      expect(screen.getByRole('status')).not.toBeInTheDocument();
    }).catch(() => {
      // if status spinner was never shown that's fine too
    });

    // The answer card should not be rendered for an empty result
    expect(screen.queryByTestId('mock-answer-card')).not.toBeInTheDocument();
    // EmptyState should appear
    expect(screen.getByText(/no results/i)).toBeInTheDocument();
  });

  it('shows the initialising state on 503 index-not-ready error', async () => {
    mockUseSearch.mockReturnValue(
      makeSearchResult({
        status: 'error',
        isError: true,
        isPending: false,
        error: new ApiError(503, 'index-not-ready'),
      }),
    );
    renderSearchPage();
    await userEvent.click(screen.getByTestId('mock-search-bar'));

    await waitFor(() => {
      expect(screen.getByText(/index is initialising/i)).toBeInTheDocument();
    });
  });

  it('calls useAuth logout() when a search returns Unauthenticated', async () => {
    let capturedAuth: ReturnType<typeof useAuth> | null = null;

    function AuthSpy() {
      capturedAuth = useAuth();
      return null;
    }

    mockUseFacets.mockReturnValue(makeFacetsResult());
    mockUseSearch.mockReturnValue(
      makeSearchResult({
        status: 'error',
        isError: true,
        isPending: false,
        error: new Unauthenticated(),
      }),
    );

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AuthProvider>
            <AuthInitialiser loggedIn>
              <AuthSpy />
              <SearchPage />
            </AuthInitialiser>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await userEvent.click(screen.getByTestId('mock-search-bar'));

    await waitFor(() => {
      expect(capturedAuth?.authenticated).toBe(false);
    });
  });

  it('passes highlightedIndex to SourceList when a citation is activated', async () => {
    mockUseSearch.mockReturnValue(
      makeSearchResult({
        status: 'success',
        isSuccess: true,
        isPending: false,
        data: successResponse,
      }),
    );
    renderSearchPage();
    await userEvent.click(screen.getByTestId('mock-search-bar'));

    await waitFor(() => {
      expect(screen.getByTestId('mock-answer-card')).toBeInTheDocument();
    });

    // Before activation: no highlight
    expect(screen.getByTestId('mock-source-list')).toHaveTextContent('highlighted:none');

    // Activate citation [1]
    await userEvent.click(screen.getByTestId('mock-citation-btn'));

    expect(screen.getByTestId('mock-source-list')).toHaveTextContent('highlighted:1');
  });
});
