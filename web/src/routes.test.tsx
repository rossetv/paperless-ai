/**
 * Tests for the app routing shell.
 *
 * The shell:
 *  - shows a loading state while setup-status / auth are resolving
 *  - routes to /setup when first-run setup is needed
 *  - routes to /login when setup is done but the user is unauthenticated
 *  - renders the protected app (SearchPage) when authenticated
 */

import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import type { SetupStatus, MeResponse } from './api/types';
import { AppRoutes } from './routes';

// --- Mock the leaf pages so routing is tested in isolation -----------------
vi.mock('./pages/LoginPage', () => ({
  LoginPage: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login'),
}));
vi.mock('./pages/SearchPage', () => ({
  SearchPage: () => React.createElement('div', { 'data-testid': 'search-page' }, 'Search'),
}));
vi.mock('./pages/SetupPage', () => ({
  SetupPage: () => React.createElement('div', { 'data-testid': 'setup-page' }, 'Setup'),
}));
vi.mock('./pages/UsersPage', () => ({
  UsersPage: () => React.createElement('div', { 'data-testid': 'users-page' }, 'Users'),
}));
vi.mock('./pages/KeysPage', () => ({
  KeysPage: () => React.createElement('div', { 'data-testid': 'keys-page' }, 'Keys'),
}));

// --- Mock the api hooks the shell calls -----------------------------------
vi.mock('./api/hooks', () => ({
  useSetupStatus: vi.fn(),
  useMe: vi.fn(),
}));

import { useSetupStatus, useMe } from './api/hooks';
const mockUseSetupStatus = useSetupStatus as ReturnType<typeof vi.fn>;
const mockUseMe = useMe as ReturnType<typeof vi.fn>;

function setupStatusResult(
  overrides: Partial<UseQueryResult<SetupStatus, Error>>,
): UseQueryResult<SetupStatus, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<SetupStatus, Error>;
}

function meResult(
  overrides: Partial<UseQueryResult<MeResponse, Error>>,
): UseQueryResult<MeResponse, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<MeResponse, Error>;
}

const SAMPLE_USER = {
  id: 1,
  username: 'alex.morgan',
  display_name: 'Alex Morgan',
  email: 'alex@home.lan',
  role: 'admin' as const,
  status: 'active' as const,
  created_at: '2026-05-01T00:00:00Z',
  last_login_at: null,
};

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AppRoutes', () => {
  it('shows a loading state while setup-status is resolving', () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isLoading: true, isPending: true }));
    mockUseMe.mockReturnValue(meResult({}));
    renderAt('/');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('routes to /setup when first-run setup is needed', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: true } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('setup-page')).toBeInTheDocument());
  });

  it('routes to /login when setup is done but the user is unauthenticated', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the search page when the user is authenticated', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects an authenticated user away from /login to the app', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/login');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects to /setup from /login when setup is still needed', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: true } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/login');
    await waitFor(() => expect(screen.getByTestId('setup-page')).toBeInTheDocument());
  });

  it('redirects away from /setup once setup is complete', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/setup');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the users page for an admin at /settings/users', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings/users');
    await waitFor(() => expect(screen.getByTestId('users-page')).toBeInTheDocument());
  });

  it('renders the keys page for an admin at /settings/keys', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings/keys');
    await waitFor(() => expect(screen.getByTestId('keys-page')).toBeInTheDocument());
  });

  it('redirects a non-admin away from /settings/users to the app', async () => {
    const member = { ...SAMPLE_USER, role: 'member' as const };
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: member } }));
    renderAt('/settings/users');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated visitor from /settings/keys to /login', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/settings/keys');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });
});
