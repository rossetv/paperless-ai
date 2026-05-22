import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
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
  ResultsScreen: ({ onPreview }: { onPreview: (id: number) => void }) =>
    React.createElement(
      'button',
      { 'data-testid': 'results', onClick: () => onPreview(9823) },
      'results',
    ),
}));
vi.mock('../features/search/NoResultsScreen/NoResultsScreen', () => ({
  NoResultsScreen: () =>
    React.createElement('div', { 'data-testid': 'no-results' }),
}));
vi.mock('../features/search/IndexNotReadyScreen/IndexNotReadyScreen', () => ({
  IndexNotReadyScreen: () =>
    React.createElement('div', { 'data-testid': 'index-not-ready' }),
}));
vi.mock('../features/search/SearchErrorScreen/SearchErrorScreen', () => ({
  SearchErrorScreen: () =>
    React.createElement('div', { 'data-testid': 'search-error' }),
}));
vi.mock('../features/search/DocumentPreviewScreen/DocumentPreviewScreen', () => ({
  DocumentPreviewScreen: ({ onClose }: { onClose: () => void }) =>
    React.createElement(
      'button',
      { 'data-testid': 'preview', onClick: onClose },
      'preview',
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
    },
  ],
  plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
  stats: { llm_calls: 1, latency_ms: 100, refined: false },
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SearchPage />
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

  it('opens the DocumentPreviewScreen when a source preview is requested', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    await userEvent.click(screen.getByTestId('results'));
    expect(screen.getByTestId('preview')).toBeInTheDocument();
  });

  it('closes the preview and returns to the results', async () => {
    mockUseSearch.mockReturnValue(
      searchResult({ isSuccess: true, data: SUCCESS_DATA }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    await userEvent.click(screen.getByTestId('results'));
    await userEvent.click(screen.getByTestId('preview'));
    expect(screen.getByTestId('results')).toBeInTheDocument();
  });
});
