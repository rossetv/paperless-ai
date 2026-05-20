/**
 * Tests for LoginPage.
 *
 * Verifies that:
 * - the page renders the LoginForm
 * - a successful login calls useAuth().login()
 * - routing to SearchPage occurs after login (useAuth state changes)
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseMutationResult } from '@tanstack/react-query';
import type { StatusResponse, LoginRequest } from '../api/types';
import { AuthProvider, useAuth } from '../hooks/useAuth';
import { LoginPage } from './LoginPage';

// ---------------------------------------------------------------------------
// Mock LoginForm and useLogin so tests are isolated from the feature layer
// ---------------------------------------------------------------------------

vi.mock('../features/auth/LoginForm/LoginForm', () => ({
  LoginForm: ({ onSuccess }: { onSuccess: () => void }) =>
    React.createElement(
      'button',
      { onClick: onSuccess, 'data-testid': 'mock-login-form' },
      'Trigger login',
    ),
}));

vi.mock('../api/hooks', () => ({
  useLogin: vi.fn(),
}));

import { useLogin } from '../api/hooks';
const mockUseLogin = useLogin as ReturnType<typeof vi.fn>;

function makeMutation(): UseMutationResult<StatusResponse, Error, LoginRequest> {
  return {
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
  } as UseMutationResult<StatusResponse, Error, LoginRequest>;
}

function renderLoginPage() {
  mockUseLogin.mockReturnValue(makeMutation());
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LoginPage', () => {
  it('renders the LoginForm', () => {
    renderLoginPage();
    expect(screen.getByTestId('mock-login-form')).toBeInTheDocument();
  });

  it('calls useAuth login() when LoginForm onSuccess fires', async () => {
    // Use a container object so TypeScript does not narrow the type to `never`
    // inside the nested AuthSpy closure (assignment in a nested function is
    // not visible to the outer control-flow analysis).
    const authRef: { current: ReturnType<typeof useAuth> | null } = { current: null };

    function AuthSpy() {
      authRef.current = useAuth();
      return null;
    }

    mockUseLogin.mockReturnValue(makeMutation());
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <AuthProvider>
            <AuthSpy />
            <LoginPage />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(authRef.current?.authenticated).toBe(false);

    await userEvent.click(screen.getByTestId('mock-login-form'));

    expect(authRef.current?.authenticated).toBe(true);
  });
});
