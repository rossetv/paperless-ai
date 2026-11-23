import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { LoginRequest, LoginResponse } from '../../../api/types';
import { Unauthenticated, ApiError } from '../../../api/client';
import { LoginScreen } from './LoginScreen';

vi.mock('../../../api/hooks', () => ({
  useLogin: vi.fn(),
}));

import { useLogin } from '../../../api/hooks';
const mockUseLogin = useLogin as ReturnType<typeof vi.fn>;

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

function renderScreen(login = makeLogin({})) {
  mockUseLogin.mockReturnValue(login);
  return render(<LoginScreen />);
}

describe('LoginScreen', () => {
  it('renders a username and a password field', () => {
    renderScreen();
    expect(screen.getByLabelText('Username')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
  });

  it('renders the sign-in submit button', () => {
    renderScreen();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('renders the keep-signed-in checkbox', () => {
    renderScreen();
    expect(screen.getByRole('checkbox', { name: /keep me signed in/i })).toBeInTheDocument();
  });

  it('shows a username validation error when too short', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText('Username'), 'ab');
    await userEvent.type(screen.getByLabelText('Password'), 'longenoughpw12');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/between 3 and 64 characters/i)).toBeInTheDocument();
  });

  it('shows a username validation error on illegal characters', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText('Username'), 'bad name!');
    await userEvent.type(screen.getByLabelText('Password'), 'longenoughpw12');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/letters, numbers/i)).toBeInTheDocument();
  });

  it('submits a password shorter than the creation minimum', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText('Username'), 'alex.morgan');
    await userEvent.type(screen.getByLabelText('Password'), 'ninechars');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mutate).toHaveBeenCalledWith(
      { username: 'alex.morgan', password: 'ninechars', remember: false },
      {},
    );
  });

  it('refuses an empty password without calling the login mutation', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText('Username'), 'alex.morgan');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
    expect(mutate).not.toHaveBeenCalled();
  });

  it('clears the previous server error when local validation fails', async () => {
    const reset = vi.fn();
    renderScreen(makeLogin({ isError: true, error: new Unauthenticated(), reset }));
    await userEvent.type(screen.getByLabelText('Username'), 'alex.morgan');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
    expect(reset).toHaveBeenCalled();
  });

  it('does not call the login mutation when validation fails', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText('Username'), 'ab');
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it('calls the login mutation with username, password and remember on valid submit', async () => {
    const mutate = vi.fn();
    renderScreen(makeLogin({ mutate }));
    await userEvent.type(screen.getByLabelText('Username'), 'alex.morgan');
    await userEvent.type(screen.getByLabelText('Password'), 'secret-password');
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
    await userEvent.type(screen.getByLabelText('Username'), 'alex.morgan');
    await userEvent.type(screen.getByLabelText('Password'), 'secret-password');
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

  it('puts focus back in the password field when a sign-in fails', async () => {
    const { rerender } = renderScreen();
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    // A browser drops focus to the body when the focused field gets disabled; jsdom does not.
    (document.activeElement as HTMLElement).blur();
    mockUseLogin.mockReturnValue(makeLogin({ isPending: true }));
    rerender(<LoginScreen />);
    mockUseLogin.mockReturnValue(makeLogin({ isError: true, error: new Unauthenticated() }));
    rerender(<LoginScreen />);
    expect(screen.getByLabelText('Password')).toHaveFocus();
  });

  it('maps Unauthenticated (401 wrong creds) to a friendly message', () => {
    renderScreen(makeLogin({ isError: true, error: new Unauthenticated() }));
    expect(screen.getByRole('alert')).toHaveTextContent(/incorrect username or password/i);
  });

  it('maps ApiError 403 (suspended account) to a friendly message', () => {
    renderScreen(makeLogin({ isError: true, error: new ApiError(403) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/account is suspended/i);
  });

  it('maps ApiError 429 to a wait-and-retry message', () => {
    renderScreen(makeLogin({ isError: true, error: new ApiError(429) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/too many attempts.*try again later/i);
  });

  it('does not promise a fixed session length for keep me signed in', () => {
    renderScreen();
    expect(screen.getByRole('checkbox', { name: /keep me signed in/i })).toBeInTheDocument();
    expect(screen.queryByText(/\d+ days/i)).not.toBeInTheDocument();
  });

  it('maps an unexpected ApiError to a generic fallback message', () => {
    renderScreen(makeLogin({ isError: true, error: new ApiError(500) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/sign-in failed/i);
  });

  it('renders the headline second line in the dim variant', () => {
    renderScreen();
    expect(screen.getByText(/you've ever filed\./i)).toBeInTheDocument();
  });

  it('toggles password visibility with the Show control', async () => {
    renderScreen();
    const password = screen.getByLabelText('Password');
    expect(password).toHaveAttribute('type', 'password');
    await userEvent.click(screen.getByRole('button', { name: /show password/i }));
    expect(password).toHaveAttribute('type', 'text');
  });
});
