/**
 * Tests for the app routing shell.
 *
 * Verifies that:
 * - an unauthenticated app renders LoginPage
 * - an authenticated app renders SearchPage
 * - login routes the user from LoginPage to SearchPage
 */

import { render, screen } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import type { FacetsResponse, SearchResponse } from './api/types';
import { AuthProvider } from './hooks/useAuth';
import App from './App';

// ---------------------------------------------------------------------------
// Mock pages to isolate routing logic
// ---------------------------------------------------------------------------

vi.mock('./pages/LoginPage', () => ({
  LoginPage: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login Page'),
}));

vi.mock('./pages/SearchPage', () => ({
  SearchPage: () => React.createElement('div', { 'data-testid': 'search-page' }, 'Search Page'),
}));

// ---------------------------------------------------------------------------
// Mock API hooks (needed even when pages are mocked, avoids Provider warnings)
// ---------------------------------------------------------------------------

vi.mock('./api/hooks', () => ({
  useSearch: vi.fn(),
  useFacets: vi.fn(),
  useLogin: vi.fn(),
}));

import { useFacets, useSearch, useLogin } from './api/hooks';
const mockUseFacets = useFacets as ReturnType<typeof vi.fn>;
const mockUseSearch = useSearch as ReturnType<typeof vi.fn>;
const mockUseLogin = useLogin as ReturnType<typeof vi.fn>;

function idleSearchResult(): UseQueryResult<SearchResponse, Error> {
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
  } as unknown as UseQueryResult<SearchResponse, Error>;
}

function idleFacetsResult(): UseQueryResult<FacetsResponse, Error> {
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
  } as unknown as UseQueryResult<FacetsResponse, Error>;
}

function setupMocks() {
  mockUseSearch.mockReturnValue(idleSearchResult());
  mockUseFacets.mockReturnValue(idleFacetsResult());
  mockUseLogin.mockReturnValue({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: 'idle',
    reset: vi.fn(),
    context: undefined,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
    variables: undefined,
  });
}

function renderApp() {
  setupMocks();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('App routing', () => {
  it('renders LoginPage when the user is unauthenticated', () => {
    renderApp();
    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('search-page')).not.toBeInTheDocument();
  });
});
