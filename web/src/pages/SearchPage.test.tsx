import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
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
  LoadingScreen: ({ activePhase }: { activePhase: string | null }) =>
    React.createElement(
      'div',
      { 'data-testid': 'loading', 'data-active-phase': activePhase ?? '' },
    ),
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
  SearchErrorScreen: ({
    onSearch,
    phaseRecords,
  }: {
    onSearch: (q: string) => void;
    phaseRecords?: unknown[];
  }) =>
    React.createElement(
      'button',
      {
        'data-testid': 'search-error',
        'data-phase-count': (phaseRecords ?? []).length,
        onClick: () => onSearch('boiler service'),
      },
      'search-error',
    ),
}));

// The streaming hook is mocked so each test drives the page into a chosen
// state. `run` is a spy; the page calls it from an effect on a non-empty query.
const mockRun = vi.fn();
vi.mock('../features/search/useStreamingSearch', () => ({
  useStreamingSearch: vi.fn(),
}));
vi.mock('../api/hooks', () => ({
  ME_QUERY_KEY: ['auth', 'me'],
}));

import { useStreamingSearch } from '../features/search/useStreamingSearch';
const mockUseStreamingSearch = useStreamingSearch as ReturnType<typeof vi.fn>;

/** Build a useStreamingSearch return value in the requested state. */
function streamState(overrides: Record<string, unknown> = {}) {
  return {
    state: {
      status: 'streaming',
      phaseRecords: [],
      activePhase: null,
      result: null,
      error: null,
      ...overrides,
    },
    run: mockRun,
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
  trace: { phases: [] },
  cost: {
    tokens: { prompt: 0, completion: 0, reasoning: 0, total: 0 },
    usd: 0,
    local: false,
    llm_calls: 1,
  },
  outcome_kind: 'answered',
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
  beforeEach(() => {
    mockRun.mockReset();
  });

  it('renders the IdleScreen when there is no query', () => {
    mockUseStreamingSearch.mockReturnValue(streamState({ status: 'idle' }));
    renderPage();
    expect(screen.getByTestId('idle')).toBeInTheDocument();
  });

  it('renders the LoadingScreen while a search is streaming', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({ status: 'streaming', activePhase: 'plan' }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('loading')).toBeInTheDocument();
  });

  it('runs the stream when a query is submitted', async () => {
    mockUseStreamingSearch.mockReturnValue(streamState({ status: 'streaming' }));
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        'npower bills',
        expect.any(Object),
      );
    });
  });

  it('renders the ResultsScreen on a done search with sources', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({ status: 'done', result: SUCCESS_DATA }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('results')).toBeInTheDocument();
  });

  it('renders the NoResultsScreen when a done search has zero sources', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'done',
        result: { ...SUCCESS_DATA, sources: [] },
      }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('no-results')).toBeInTheDocument();
  });

  it('renders the IndexNotReadyScreen on a 503 stream error', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'error',
        error: { status: 503, message: 'index not ready' },
      }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('index-not-ready')).toBeInTheDocument();
  });

  it('renders the SearchErrorScreen on a generic stream error', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'error',
        error: { status: 500, message: 'boom' },
      }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('search-error')).toBeInTheDocument();
  });

  it('passes the partial phase records to the error screen', async () => {
    const phaseRecords = [
      { phase: 'plan', label: 'Planning', detail: {}, tokens: null, cost: null, ms: 1 },
    ];
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'error',
        error: { status: 500, message: 'boom' },
        phaseRecords,
      }),
    );
    renderPage();
    await userEvent.click(screen.getByTestId('idle'));
    expect(screen.getByTestId('search-error')).toHaveAttribute(
      'data-phase-count',
      '1',
    );
  });

  it('invalidates the me query on a 401 stream error', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'error',
        error: { status: 401, message: 'unauthorised' },
      }),
    );
    // Spy on the prototype BEFORE render — mounting at /?q=invoice fires the
    // invalidation effect immediately, before a per-instance spy could attach.
    const invalidateSpy = vi.spyOn(
      QueryClient.prototype,
      'invalidateQueries',
    );
    renderPage('/?q=invoice');
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['auth', 'me'],
      });
    });
    invalidateSpy.mockRestore();
  });

  it('shows the idle hero (not an error) while a 401 redirect resolves', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({
        status: 'error',
        error: { status: 401, message: 'unauthorised' },
      }),
    );
    renderPage('/?q=invoice');
    // A 401 renders the calm idle hero, not the error screen.
    expect(screen.getByTestId('idle')).toBeInTheDocument();
    expect(screen.queryByTestId('search-error')).not.toBeInTheDocument();
  });

  it('runs a second, different search from the results view', async () => {
    // Regression: once a search ran, `query` never reset and only the idle
    // screen had an editable field — the user was stranded on the results
    // screen with no way to start a fresh search short of a full reload.
    mockUseStreamingSearch.mockReturnValue(
      streamState({ status: 'done', result: SUCCESS_DATA }),
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
    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith(
        'rolling-blackout refunds',
        expect.any(Object),
      );
    });
  });

  it('mounting at /?q=invoice triggers the search', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({ status: 'done', result: SUCCESS_DATA }),
    );
    renderPage('/?q=invoice');
    // The results screen renders immediately — no interaction needed.
    await waitFor(() => {
      expect(screen.getByTestId('results')).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(mockRun).toHaveBeenCalledWith('invoice', expect.any(Object));
    });
  });

  it('mounting at / shows the IdleScreen', () => {
    mockUseStreamingSearch.mockReturnValue(streamState({ status: 'idle' }));
    renderPage('/');
    expect(screen.getByTestId('idle')).toBeInTheDocument();
  });

  it('does not run a search when there is no query', () => {
    mockUseStreamingSearch.mockReturnValue(streamState({ status: 'idle' }));
    renderPage('/');
    expect(mockRun).not.toHaveBeenCalled();
  });

  it('submitting a search from / updates the URL to /?q=…', async () => {
    mockUseStreamingSearch.mockReturnValue(streamState({ status: 'streaming' }));
    const { locationRef } = renderPage('/');
    await userEvent.click(screen.getByTestId('idle'));
    await waitFor(() => {
      expect(locationRef.current).toBe('/?q=npower+bills');
    });
  });

  it('opening a preview navigates to /document/<id> with the search context preserved', async () => {
    mockUseStreamingSearch.mockReturnValue(
      streamState({ status: 'done', result: SUCCESS_DATA }),
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
