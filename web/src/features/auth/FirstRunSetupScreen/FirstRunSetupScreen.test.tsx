import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { SetupRequest, SetupResponse } from '../../../api/types';
import { ApiError } from '../../../api/client';
import { FirstRunSetupScreen } from './FirstRunSetupScreen';

vi.mock('../../../api/hooks', () => ({
  useSetup: vi.fn(),
}));

import { useSetup } from '../../../api/hooks';
const mockUseSetup = useSetup as ReturnType<typeof vi.fn>;

function makeSetup(
  overrides: Partial<UseMutationResult<SetupResponse, Error, SetupRequest>>,
): UseMutationResult<SetupResponse, Error, SetupRequest> {
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
  } as UseMutationResult<SetupResponse, Error, SetupRequest>;
}

function renderScreen(setup = makeSetup({})) {
  mockUseSetup.mockReturnValue(setup);
  return render(<FirstRunSetupScreen />);
}

describe('FirstRunSetupScreen', () => {
  it('renders the setup token, username, password and confirm fields', () => {
    renderScreen();
    expect(screen.getByLabelText(/setup token/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
  });

  it('renders the create-admin submit button', () => {
    renderScreen();
    expect(screen.getByRole('button', { name: /create admin account/i })).toBeInTheDocument();
  });

  it('explains where to find the setup token', () => {
    renderScreen();
    expect(screen.getByText(/container logs/i)).toBeInTheDocument();
  });

  it('shows a validation error for a short username', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/setup token/i), 'tok');
    await userEvent.type(screen.getByLabelText(/^username/i), 'ab');
    await userEvent.type(screen.getByLabelText(/^password/i), 'longenoughpw12');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'longenoughpw12');
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(screen.getByText(/between 3 and 64 characters/i)).toBeInTheDocument();
  });

  it('shows a validation error for a short password', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/setup token/i), 'tok');
    await userEvent.type(screen.getByLabelText(/^username/i), 'admin');
    await userEvent.type(screen.getByLabelText(/^password/i), 'short');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument();
  });

  it('shows a mismatch error when the passwords differ', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/setup token/i), 'tok');
    await userEvent.type(screen.getByLabelText(/^username/i), 'admin');
    await userEvent.type(screen.getByLabelText(/^password/i), 'longenoughpw12');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'different1-pw12');
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it('requires a non-empty setup token', async () => {
    renderScreen();
    await userEvent.type(screen.getByLabelText(/^username/i), 'admin');
    await userEvent.type(screen.getByLabelText(/^password/i), 'longenoughpw12');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'longenoughpw12');
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(screen.getByText(/enter the setup token/i)).toBeInTheDocument();
  });

  it('does not call the setup mutation when validation fails', async () => {
    const mutate = vi.fn();
    renderScreen(makeSetup({ mutate }));
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(mutate).not.toHaveBeenCalled();
  });

  it('calls the setup mutation with token, username and password on valid submit', async () => {
    const mutate = vi.fn();
    renderScreen(makeSetup({ mutate }));
    await userEvent.type(screen.getByLabelText(/setup token/i), 'the-setup-token');
    await userEvent.type(screen.getByLabelText(/^username/i), 'admin');
    await userEvent.type(screen.getByLabelText(/^password/i), 'longenoughpw12');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'longenoughpw12');
    await userEvent.click(screen.getByRole('button', { name: /create admin account/i }));
    expect(mutate).toHaveBeenCalledWith(
      { token: 'the-setup-token', username: 'admin', password: 'longenoughpw12' },
      expect.anything(),
    );
  });

  it('disables the submit button while the mutation is pending', () => {
    renderScreen(makeSetup({ isPending: true }));
    expect(screen.getByRole('button', { name: /creating/i })).toBeDisabled();
  });

  it('maps ApiError 403 (bad setup token) to a friendly message', () => {
    renderScreen(makeSetup({ isError: true, error: new ApiError(403) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/invalid setup token/i);
  });

  it('maps ApiError 409 (already set up) to a friendly message', () => {
    renderScreen(makeSetup({ isError: true, error: new ApiError(409) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/already set up/i);
  });

  it('maps an unexpected error to a generic fallback message', () => {
    renderScreen(makeSetup({ isError: true, error: new ApiError(500) }));
    expect(screen.getByRole('alert')).toHaveTextContent(/setup failed/i);
  });
});
