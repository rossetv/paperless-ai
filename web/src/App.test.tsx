/**
 * Smoke tests for the App component.
 *
 * App delegates routing to AppRoutes; these tests verify the provider
 * tree is wired correctly and the auth-gated routing behaves as expected.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { AuthProvider } from './hooks/useAuth';
import App from './App';

// Mock pages so the smoke test does not need the full feature tree
vi.mock('./pages/LoginPage', () => ({
  LoginPage: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login'),
}));

vi.mock('./pages/SearchPage', () => ({
  SearchPage: () => React.createElement('div', { 'data-testid': 'search-page' }, 'Search'),
}));

/** Renders App with the full provider stack it requires. */
function renderApp(): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

describe('App', () => {
  it('renders the login page when unauthenticated', () => {
    renderApp();
    expect(screen.getByTestId('login-page')).toBeInTheDocument();
  });
});
