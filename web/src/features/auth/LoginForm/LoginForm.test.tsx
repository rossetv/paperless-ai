import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { StatusResponse, LoginRequest } from '../../../api/types';
import { LoginForm } from './LoginForm';

// ---------------------------------------------------------------------------
// Mock useLogin so tests do not need a real QueryClient or network
// ---------------------------------------------------------------------------

vi.mock('../../../api/hooks', () => ({
  useLogin: vi.fn(),
}));

import { useLogin } from '../../../api/hooks';
const mockUseLogin = useLogin as ReturnType<typeof vi.fn>;

/** Build a minimal UseMutationResult stub. */
function makeMutation(
  overrides: Partial<UseMutationResult<StatusResponse, Error, LoginRequest>>,
): UseMutationResult<StatusResponse, Error, LoginRequest> {
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
  } as UseMutationResult<StatusResponse, Error, LoginRequest>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const onSuccess = vi.fn();

function renderForm(
  mutation: UseMutationResult<StatusResponse, Error, LoginRequest>,
) {
  mockUseLogin.mockReturnValue(mutation);
  render(<LoginForm onSuccess={onSuccess} />);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LoginForm', () => {
  beforeEach(() => {
    onSuccess.mockReset();
  });

  it('renders an API key input of type password', () => {
    renderForm(makeMutation({}));
    const input = screen.getByLabelText(/api key/i);
    expect(input).toHaveAttribute('type', 'password');
  });

  it('renders a submit button', () => {
    renderForm(makeMutation({}));
    expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument();
  });

  it('calls mutate with the typed api key on submit', async () => {
    const mutate = vi.fn();
    renderForm(makeMutation({ mutate }));

    await userEvent.type(screen.getByLabelText(/api key/i), 'secret-key');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    expect(mutate).toHaveBeenCalledWith(
      { api_key: 'secret-key' },
      expect.anything(),
    );
  });

  it('disables the submit button and shows a loading state while pending', () => {
    renderForm(makeMutation({ isPending: true }));
    const button = screen.getByRole('button', { name: /logging in/i });
    expect(button).toBeDisabled();
  });

  it('surfaces an error message on auth failure (wrong key → 401)', () => {
    renderForm(
      makeMutation({
        isError: true,
        error: new Error('Invalid API key'),
      }),
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid api key/i);
  });

  it('calls onSuccess when the mutation succeeds', async () => {
    const mutate = vi.fn().mockImplementation((_vars, opts) => {
      opts?.onSuccess?.({ status: 'ok' });
    });
    renderForm(makeMutation({ mutate }));

    await userEvent.type(screen.getByLabelText(/api key/i), 'good-key');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it('does not store or echo the api key after submit', async () => {
    const mutate = vi.fn().mockImplementation((_vars, opts) => {
      opts?.onSuccess?.({ status: 'ok' });
    });
    renderForm(makeMutation({ mutate }));

    await userEvent.type(screen.getByLabelText(/api key/i), 'my-secret');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    // The input value is cleared in the onSuccess callback
    expect(screen.getByLabelText(/api key/i)).toHaveValue('');
  });

  it('retains the typed value and enables the submit button after a failed login', async () => {
    // Simulate a mutation that fails (stays in error state, never calls onSuccess)
    const mutate = vi.fn();
    renderForm(
      makeMutation({
        mutate,
        isError: true,
        error: new Error('Invalid API key'),
      }),
    );

    await userEvent.type(screen.getByLabelText(/api key/i), 'bad-key');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    // The field must still contain the typed key so the user can correct it
    expect(screen.getByLabelText(/api key/i)).toHaveValue('bad-key');
    // The submit button must be enabled (not disabled) so the user can retry
    expect(screen.getByRole('button', { name: /log in/i })).not.toBeDisabled();
  });
});
