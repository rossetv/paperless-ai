/**
 * Smoke tests for the App component.
 *
 * App delegates routing to AppRoutes; this test verifies the provider tree
 * is wired and the bootstrap gate routes an unauthenticated, set-up install
 * to the login page.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import App from './App';

vi.mock('./pages/LoginPage', () => ({
  LoginPage: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login'),
}));
vi.mock('./pages/SearchPage', () => ({
  SearchPage: () => React.createElement('div', { 'data-testid': 'search-page' }, 'Search'),
}));
vi.mock('./pages/SetupPage', () => ({
  SetupPage: () => React.createElement('div', { 'data-testid': 'setup-page' }, 'Setup'),
}));

vi.mock('./api/hooks', () => ({
  useSetupStatus: vi.fn(),
  useMe: vi.fn(),
}));

import { useSetupStatus, useMe } from './api/hooks';
const mockUseSetupStatus = useSetupStatus as ReturnType<typeof vi.fn>;
const mockUseMe = useMe as ReturnType<typeof vi.fn>;

describe('App', () => {
  it('renders the login page when set up and unauthenticated', async () => {
    mockUseSetupStatus.mockReturnValue({
      data: { needed: false },
      isLoading: false,
      isError: false,
      isSuccess: true,
      isPending: false,
      error: null,
    });
    mockUseMe.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      isSuccess: false,
      isPending: false,
      error: new Error('Unauthenticated'),
    });

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });
});
