import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { UserResponse } from '../../../api/types';
import { UserEditDrawer } from './UserEditDrawer';

vi.mock('../../../api/hooks', () => ({
  useCreateUser: vi.fn(),
  useUpdateUser: vi.fn(),
  useDeleteUser: vi.fn(),
}));

import { useCreateUser, useUpdateUser, useDeleteUser } from '../../../api/hooks';
const mockCreate = useCreateUser as ReturnType<typeof vi.fn>;
const mockUpdate = useUpdateUser as ReturnType<typeof vi.fn>;
const mockDelete = useDeleteUser as ReturnType<typeof vi.fn>;

const SAMPLE_USER = {
  id: 2,
  username: 'sam.patel',
  display_name: 'Sam Patel',
  email: 'sam@home.lan',
  role: 'member' as const,
  status: 'active' as const,
  created_at: '2026-01-01T00:00:00Z',
  last_login_at: '2026-05-20T00:00:00Z',
};

// A generic mutation stub. `mutateAsync` is the call the drawer awaits.
function stubMutation<TData, TVars>(
  mutateAsync: (vars: TVars) => Promise<TData>,
  overrides: Partial<UseMutationResult<TData, Error, TVars>> = {},
): UseMutationResult<TData, Error, TVars> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(mutateAsync),
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
  } as UseMutationResult<TData, Error, TVars>;
}

const okUser: UserResponse = { user: SAMPLE_USER };

beforeEach(() => {
  mockCreate.mockReturnValue(stubMutation(async () => okUser));
  mockUpdate.mockReturnValue(stubMutation(async () => okUser));
  mockDelete.mockReturnValue(stubMutation(async () => undefined));
});

describe('UserEditDrawer — create mode', () => {
  it('renders a create-titled dialog when user is null', () => {
    render(<UserEditDrawer user={null} isSelf={false} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: /add user/i })).toBeInTheDocument();
  });

  it('shows an editable username field in create mode', () => {
    render(<UserEditDrawer user={null} isSelf={false} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/username/i)).not.toBeDisabled();
  });

  it('rejects a too-short username on submit', async () => {
    render(<UserEditDrawer user={null} isSelf={false} onClose={vi.fn()} />);
    // Wait for the Modal focus-trap rAF to settle before driving the keyboard.
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/username/i), 'ab');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'password1');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'password1');
    await userEvent.click(screen.getByRole('button', { name: /create user/i }));
    expect(screen.getByText(/username must be 3/i)).toBeInTheDocument();
  });

  it('rejects a short password on submit', async () => {
    render(<UserEditDrawer user={null} isSelf={false} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/username/i), 'sam.patel');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'short');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /create user/i }));
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
  });

  it('rejects mismatched passwords on submit', async () => {
    render(<UserEditDrawer user={null} isSelf={false} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/username/i), 'sam.patel');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'password1');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'password2');
    await userEvent.click(screen.getByRole('button', { name: /create user/i }));
    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
  });

  it('calls createUser and closes on a valid submit', async () => {
    const onClose = vi.fn();
    const mutateAsync = vi.fn().mockResolvedValue(okUser);
    mockCreate.mockReturnValue(stubMutation(mutateAsync));
    render(<UserEditDrawer user={null} isSelf={false} onClose={onClose} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/username/i), 'sam.patel');
    await userEvent.type(screen.getByLabelText(/display name/i), 'Sam Patel');
    await userEvent.type(screen.getByLabelText(/^new password/i), 'password1');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'password1');
    await userEvent.click(screen.getByRole('button', { name: /create user/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0][0]).toMatchObject({
      username: 'sam.patel',
      password: 'password1',
      role: 'member',
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe('UserEditDrawer — edit mode', () => {
  it('renders an edit-titled dialog and a read-only username', () => {
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: /edit/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeDisabled();
  });

  it('pre-fills the display name and email', () => {
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={vi.fn()} />);
    expect(screen.getByLabelText(/display name/i)).toHaveValue('Sam Patel');
    expect(screen.getByLabelText(/email/i)).toHaveValue('sam@home.lan');
  });

  it('submits only changed fields via updateUser', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(okUser);
    mockUpdate.mockReturnValue(stubMutation(mutateAsync));
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    const name = screen.getByLabelText(/display name/i);
    await userEvent.clear(name);
    await userEvent.type(name, 'Samuel Patel');
    await userEvent.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0][0]).toEqual({
      id: 2,
      body: { display_name: 'Samuel Patel' },
    });
  });

  it('keeps the password unset when the field is left empty', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(okUser);
    mockUpdate.mockReturnValue(stubMutation(mutateAsync));
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalled());
    expect(mutateAsync.mock.calls[0][0].body).not.toHaveProperty('password');
  });

  it('calls deleteUser when delete is confirmed', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockDelete.mockReturnValue(stubMutation(mutateAsync));
    const onClose = vi.fn();
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /delete account/i }));
    // a confirm step appears — confirm it
    await userEvent.click(screen.getByRole('button', { name: /^confirm delete/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(2));
  });

  it('disables delete and suspend for one\'s own account', () => {
    render(<UserEditDrawer user={SAMPLE_USER} isSelf onClose={vi.fn()} />);
    expect(screen.getByRole('button', { name: /delete account/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /suspend/i })).toBeDisabled();
  });

  it('surfaces a server error message when the mutation rejects', async () => {
    const mutateAsync = vi.fn().mockRejectedValue(new Error('boom'));
    mockUpdate.mockReturnValue(stubMutation(mutateAsync));
    render(<UserEditDrawer user={SAMPLE_USER} isSelf={false} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    const name = screen.getByLabelText(/display name/i);
    await userEvent.clear(name);
    await userEvent.type(name, 'Changed');
    await userEvent.click(screen.getByRole('button', { name: /^save/i }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not save/i),
    );
  });
});
