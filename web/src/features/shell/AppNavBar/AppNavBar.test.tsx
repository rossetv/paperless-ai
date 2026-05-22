import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { UseMutationResult } from '@tanstack/react-query';
import { AppNavBar } from './AppNavBar';

// --- Mock auth + logout --------------------------------------------------
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: vi.fn(),
}));
vi.mock('../../../api/hooks', () => ({
  useLogout: vi.fn(),
}));

import { useAuth } from '../../../hooks/useAuth';
import { useLogout } from '../../../api/hooks';
const mockUseAuth = useAuth as ReturnType<typeof vi.fn>;
const mockUseLogout = useLogout as ReturnType<typeof vi.fn>;

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

function makeLogout(
  overrides: Partial<UseMutationResult<void, Error, void>> = {},
): UseMutationResult<void, Error, void> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
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
  } as UseMutationResult<void, Error, void>;
}

function renderNavBar(logout = makeLogout()) {
  mockUseAuth.mockReturnValue({
    user: SAMPLE_USER,
    role: 'admin',
    isAuthenticated: true,
    isLoading: false,
  });
  mockUseLogout.mockReturnValue(logout);
  return render(
    <MemoryRouter>
      <AppNavBar />
    </MemoryRouter>,
  );
}

describe('AppNavBar', () => {
  it('renders a navigation landmark', () => {
    const { container } = renderNavBar();
    expect(container.querySelector('nav')).toBeInTheDocument();
  });

  it('renders the Paperless AI wordmark', () => {
    renderNavBar();
    expect(screen.getByText(/paperless/i)).toBeInTheDocument();
  });

  it('renders the Search nav link', () => {
    renderNavBar();
    expect(screen.getByRole('link', { name: /search/i })).toBeInTheDocument();
  });

  it('renders the user-menu trigger with the user initials', () => {
    renderNavBar();
    // "Alex Morgan" → initials "AM"
    expect(screen.getByText('AM')).toBeInTheDocument();
  });

  it('opens the user menu and shows the display name', async () => {
    renderNavBar();
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    expect(screen.getByText('Alex Morgan')).toBeInTheDocument();
  });

  it('runs the logout mutation when Sign out is chosen', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    renderNavBar(makeLogout({ mutateAsync }));
    await userEvent.click(screen.getByRole('button', { name: /account menu/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));
    expect(mutateAsync).toHaveBeenCalledTimes(1);
  });

  it('shows a Settings link for an admin user', () => {
    renderNavBar();
    expect(screen.getByRole('link', { name: /settings/i })).toBeInTheDocument();
  });

  it('hides the Settings link for a non-admin user', () => {
    mockUseAuth.mockReturnValue({
      user: { ...SAMPLE_USER, role: 'member' },
      role: 'member',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('link', { name: /settings/i })).not.toBeInTheDocument();
  });

  it('renders nothing when there is no authenticated user', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      role: null,
      isAuthenticated: false,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    const { container } = render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(container.querySelector('nav')).not.toBeInTheDocument();
  });
});
