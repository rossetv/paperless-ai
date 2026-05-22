import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import type { UsersResponse, User } from '../../../api/types';
import { UsersScreen } from './UsersScreen';

vi.mock('../../../api/hooks', () => ({ useUsers: vi.fn() }));
vi.mock('../../../hooks/useAuth', () => ({ useAuth: vi.fn() }));
// The drawer is a separate unit — stub it so this test is about the screen.
vi.mock('../UserEditDrawer/UserEditDrawer', () => ({
  UserEditDrawer: ({ user, onClose }: { user: User | null; onClose: () => void }) => (
    <div data-testid="user-drawer" data-mode={user === null ? 'create' : 'edit'}>
      <button type="button" onClick={onClose}>
        close-drawer
      </button>
    </div>
  ),
}));

import { useUsers } from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';
const mockUseUsers = useUsers as ReturnType<typeof vi.fn>;
const mockUseAuth = useAuth as ReturnType<typeof vi.fn>;

const USERS: User[] = [
  {
    id: 1,
    username: 'alex.morgan',
    display_name: 'Alex Morgan',
    email: 'alex@home.lan',
    role: 'admin',
    status: 'active',
    created_at: '2024-09-12T00:00:00Z',
    last_login_at: '2026-05-22T00:00:00Z',
  },
  {
    id: 2,
    username: 'sam.patel',
    display_name: 'Sam Patel',
    email: 'sam@home.lan',
    role: 'member',
    status: 'active',
    created_at: '2025-01-01T00:00:00Z',
    last_login_at: '2026-05-19T00:00:00Z',
  },
  {
    id: 6,
    username: 'pat.kim',
    display_name: 'Pat Kim',
    email: 'pat@home.lan',
    role: 'member',
    status: 'suspended',
    created_at: '2025-02-01T00:00:00Z',
    last_login_at: '2026-04-20T00:00:00Z',
  },
];

function usersResult(
  overrides: Partial<UseQueryResult<UsersResponse, Error>>,
): UseQueryResult<UsersResponse, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<UsersResponse, Error>;
}

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={['/settings/users']}>
      <UsersScreen />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockUseAuth.mockReturnValue({
    user: USERS[0],
    role: 'admin',
    isAuthenticated: true,
    isLoading: false,
  });
});

describe('UsersScreen', () => {
  it('shows a loading status while users are loading', () => {
    mockUseUsers.mockReturnValue(usersResult({ isLoading: true, isPending: true }));
    renderScreen();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an error message when the users query fails', () => {
    mockUseUsers.mockReturnValue(
      usersResult({ isError: true, error: new Error('nope') }),
    );
    renderScreen();
    expect(screen.getByText(/could not load users/i)).toBeInTheDocument();
  });

  it('renders the Users page title', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    expect(screen.getByRole('heading', { level: 1, name: 'Users' })).toBeInTheDocument();
  });

  it('renders a table row for each user', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    expect(screen.getByText('Alex Morgan')).toBeInTheDocument();
    expect(screen.getByText('Sam Patel')).toBeInTheDocument();
    expect(screen.getByText('Pat Kim')).toBeInTheDocument();
  });

  it('shows the total-accounts stat', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    expect(screen.getByText('total accounts')).toBeInTheDocument();
    // 3 users total
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('marks the current user with a "You" indicator', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    expect(screen.getByText('You')).toBeInTheDocument();
  });

  it('renders the user initials in the row', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    // "Alex Morgan" -> "AM"
    expect(screen.getByText('AM')).toBeInTheDocument();
  });

  it('filters the table by the search box', async () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    await userEvent.type(screen.getByPlaceholderText(/search users/i), 'pat');
    expect(screen.getByText('Pat Kim')).toBeInTheDocument();
    expect(screen.queryByText('Alex Morgan')).not.toBeInTheDocument();
  });

  it('opens the create drawer when "Add user" is clicked', async () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /add user/i }));
    const drawer = screen.getByTestId('user-drawer');
    expect(drawer).toHaveAttribute('data-mode', 'create');
  });

  it('opens the edit drawer when a row Edit is clicked', async () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    const samRow = screen.getByText('Sam Patel').closest('tr') as HTMLElement;
    await userEvent.click(within(samRow).getByRole('button', { name: /edit/i }));
    expect(screen.getByTestId('user-drawer')).toHaveAttribute('data-mode', 'edit');
  });

  it('closes the drawer when the drawer asks to close', async () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: USERS } }));
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /add user/i }));
    await userEvent.click(screen.getByRole('button', { name: 'close-drawer' }));
    await waitFor(() =>
      expect(screen.queryByTestId('user-drawer')).not.toBeInTheDocument(),
    );
  });

  it('renders an empty message when there are no users', () => {
    mockUseUsers.mockReturnValue(usersResult({ isSuccess: true, data: { users: [] } }));
    renderScreen();
    expect(screen.getByText(/no users/i)).toBeInTheDocument();
  });
});
