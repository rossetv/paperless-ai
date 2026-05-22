import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query';
import type { LoginRequest, LoginResponse, PublicStats } from '../../../api/types';
import { LoginScreen } from './LoginScreen';

// --- Mock the api hooks ---------------------------------------------------
vi.mock('../../../api/hooks', () => ({
  useLogin: vi.fn(),
  usePublicStats: vi.fn(),
}));

import { useLogin, usePublicStats } from '../../../api/hooks';
const mockUseLogin = useLogin as ReturnType<typeof vi.fn>;
const mockUsePublicStats = usePublicStats as ReturnType<typeof vi.fn>;

function makeLogin(
  overrides: Partial<UseMutationResult<LoginResponse, Error, LoginRequest>>,
): UseMutationResult<LoginResponse, Error, LoginRequest> {
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
    ...overrides,
  } as UseMutationResult<LoginResponse, Error, LoginRequest>;
}

function makeStats(
  overrides: Partial<UseQueryResult<PublicStats, Error>>,
): UseQueryResult<PublicStats, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<PublicStats, Error>;
}

function renderScreen(
  login = makeLogin({}),
  stats = makeStats({ isError: true }),
) {
  mockUseLogin.mockReturnValue(login);
  mockUsePublicStats.mockReturnValue(stats);
  return render(<LoginScreen />);
}

describe('LoginScreen', () => {
  it('renders a username and a password field', () => {
    renderScreen();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
  });

  it('renders the sign-in submit button', () => {
    renderScreen();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the keep-signed-in checkbox', () => {
    renderScreen();
    expect(screen.getByRole('checkbox', { name: /keep me signed in/i })).toBeInTheDocument();
  });

  it('renders the cookie / API-key explanatory note', () => {
    renderScreen();
    expect(screen.getByText(/signed session cookie/i)).toBeInTheDocument();
    expect(screen.getByText(/api keys are for the rest api/i)).toBeInTheDocument();
  });

  it('shows a username validation error when too short', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/username/i), 'ab');
    await userEvent.type(screen.getByLabelText(/password/i), 'longenough');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/at least 3 characters/i)).toBeInTheDocument();
  });

  it('shows a username validation error on illegal characters', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/username/i), 'bad name!');
    await userEvent.type(screen.getByLabelText(/password/i), 'longenough');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/letters, numbers/i)).toBeInTheDocument();
  });

  it('shows a password validation error when shorter than 8 characters', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/username/i), 'alex.morgan');
    await userEvent.type(screen.getByLabelText(/password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
  });

  it('does not call the login mutation when validation fails', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText(/username/i), 'ab');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it('calls the login mutation with username, password and remember on valid submit', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText(/username/i), 'alex.morgan');
    await userEvent.type(screen.getByLabelText(/password/i), 'secret-password');
    await userEvent.click(screen.getByRole('checkbox', { name: /keep me signed in/i }));
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mutate).toHaveBeenCalledWith(
      { username: 'alex.morgan', password: 'secret-password', remember: true },
      expect.anything(),
    );
  });

  it('defaults remember to false when the checkbox is untouched', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText(/username/i), 'alex.morgan');
    await userEvent.type(screen.getByLabelText(/password/i), 'secret-password');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mutate).toHaveBeenCalledWith(
      { username: 'alex.morgan', password: 'secret-password', remember: false },
      expect.anything(),
    );
  });

  it('disables the submit button while the mutation is pending', () => {
    renderScreen(makeLogin({ isPending: true }));
    expect(screen.getByRole('button', { name: /signing in/i })).toBeDisabled();
  });

  it('surfaces an invalid-credentials error as an alert', () => {
    renderScreen(makeLogin({ isError: true, error: new Error('Invalid username or password') }));
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid username or password/i);
  });

  it('shows the public stats when the query succeeds', () => {
    renderScreen(
      makeLogin({}),
      makeStats({ isSuccess: true, data: { document_count: 14238, chunk_count: 187000 } }),
    );
    expect(screen.getByText('14,238')).toBeInTheDocument();
  });

  it('omits the stat numbers gracefully when the public-stats query fails', () => {
    renderScreen(makeLogin({}), makeStats({ isError: true }));
    // The stat labels never render without data — querying any number fails.
    expect(screen.queryByText(/documents indexed/i)).not.toBeInTheDocument();
  });

  it('toggles password visibility with the Show control', async () => {
    renderScreen();
    const password = screen.getByLabelText(/password/i);
    expect(password).toHaveAttribute('type', 'password');
    await userEvent.click(screen.getByRole('button', { name: /show password/i }));
    expect(password).toHaveAttribute('type', 'text');
  });
});
