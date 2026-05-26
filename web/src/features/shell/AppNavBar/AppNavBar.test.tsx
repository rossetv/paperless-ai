import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { UseMutationResult } from '@tanstack/react-query';
import { AppNavBar } from './AppNavBar';

// --- Mock auth + logout + stats ------------------------------------------
vi.mock('../../../hooks/useAuth', () => ({
  useAuth: vi.fn(),
}));
vi.mock('../../../api/hooks', () => ({
  useLogout: vi.fn(),
  useStats: vi.fn(),
}));

import { useAuth } from '../../../hooks/useAuth';
import { useLogout, useStats } from '../../../api/hooks';
const mockUseAuth = useAuth as ReturnType<typeof vi.fn>;
const mockUseLogout = useLogout as ReturnType<typeof vi.fn>;
const mockUseStats = useStats as ReturnType<typeof vi.fn>;

/** Default stats — resolved with a small document set. */
function makeStats(overrides: Record<string, unknown> = {}) {
  return {
    isSuccess: true,
    data: {
      document_count: 42,
      chunk_count: 1000,
      last_reconcile_at: null,
      embedding_model: 'text-embedding-3-small',
      ...overrides,
    },
    isError: false,
    isPending: false,
  };
}

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
  mockUseStats.mockReturnValue(makeStats());
  return render(
    <MemoryRouter>
      <AppNavBar />
    </MemoryRouter>,
  );
}

function renderNavBarAt(path: string) {
  mockUseAuth.mockReturnValue({
    user: SAMPLE_USER,
    role: 'admin',
    isAuthenticated: true,
    isLoading: false,
  });
  mockUseLogout.mockReturnValue(makeLogout());
  mockUseStats.mockReturnValue(makeStats());
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppNavBar />
    </MemoryRouter>,
  );
}

/**
 * Return the desktop NavBar `<nav>` element (the first `nav` in the DOM).
 *
 * `AppNavBar` renders three navigation elements:
 *   1. The desktop NavBar glass bar (`<nav aria-label="Main navigation">`)
 *   2. The MobileTopBar (`<div role="banner">`)
 *   3. The BottomTabBar (`<nav aria-label="Mobile navigation">`)
 *
 * Tests that query by link name must scope to one surface to avoid
 * `getMultipleElementsFoundError`. `desktopNav` scopes to the first nav
 * (the desktop bar) — every link appears there at least once.
 */
function desktopNav(container: HTMLElement): HTMLElement {
  const nav = container.querySelector('nav[aria-label="Main navigation"]');
  if (nav === null) throw new Error('Desktop NavBar not found');
  return nav as HTMLElement;
}

describe('AppNavBar', () => {
  it('renders a navigation landmark', () => {
    const { container } = renderNavBar();
    expect(container.querySelector('nav')).toBeInTheDocument();
  });

  it('renders the Paperless AI wordmark', () => {
    renderNavBar();
    // Wordmark appears in both desktop and mobile — first match is fine.
    expect(screen.getAllByText(/paperless/i)[0]).toBeInTheDocument();
  });

  it('renders the Search nav link', () => {
    const { container } = renderNavBar();
    // Both desktop and mobile surfaces render a Search link — scope to desktop.
    expect(
      within(desktopNav(container)).getByRole('link', { name: /search/i }),
    ).toBeInTheDocument();
  });

  it('renders the user-menu trigger with the user initials', () => {
    renderNavBar();
    // "Alex Morgan" → initials "AM". Appears in both surfaces; first match suffices.
    expect(screen.getAllByText('AM')[0]).toBeInTheDocument();
  });

  it('opens the user menu and shows the display name', async () => {
    renderNavBar();
    // First account-menu button is in the desktop bar.
    // getAllByRole always returns at least one element (throws if empty).
    const firstMenuBtn = screen.getAllByRole('button', { name: /account menu/i }).at(0) as HTMLElement;
    await userEvent.click(firstMenuBtn);
    expect(screen.getByText('Alex Morgan')).toBeInTheDocument();
  });

  it('runs the logout mutation when Sign out is chosen', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    renderNavBar(makeLogout({ mutateAsync }));
    // getAllByRole always returns at least one element (throws if empty).
    const firstMenuBtn = screen.getAllByRole('button', { name: /account menu/i }).at(0) as HTMLElement;
    await userEvent.click(firstMenuBtn);
    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));
    expect(mutateAsync).toHaveBeenCalledTimes(1);
  });

  it('shows a Settings link for an admin user', () => {
    const { container } = renderNavBar();
    expect(
      within(desktopNav(container)).getByRole('link', { name: /settings/i }),
    ).toBeInTheDocument();
  });

  it('hides the Settings link for a non-admin user', () => {
    mockUseAuth.mockReturnValue({
      user: { ...SAMPLE_USER, role: 'member' },
      role: 'member',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue(makeStats());
    render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(screen.queryByRole('link', { name: /settings/i })).not.toBeInTheDocument();
  });

  it('renders a Library link pointing at /library', () => {
    mockUseAuth.mockReturnValue({
      user: { id: 1, username: 'amy', display_name: 'Amy', email: null, role: 'member', status: 'active', created_at: '', last_login_at: null },
      role: 'member',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue(makeStats());
    const { container } = render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(
      within(desktopNav(container)).getByRole('link', { name: 'Library' }),
    ).toHaveAttribute('href', '/library');
  });

  it('marks the Library link active when on /library', () => {
    mockUseAuth.mockReturnValue({
      user: { id: 1, username: 'amy', display_name: 'Amy', email: null, role: 'member', status: 'active', created_at: '', last_login_at: null },
      role: 'member',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue(makeStats());
    const { container } = render(
      <MemoryRouter initialEntries={['/library']}>
        <AppNavBar />
      </MemoryRouter>,
    );
    const link = within(desktopNav(container)).getByRole('link', { name: 'Library' });
    expect(link).toHaveAttribute('aria-current', 'page');
  });

  it('renders nothing when there is no authenticated user', () => {
    mockUseAuth.mockReturnValue({
      user: null,
      role: null,
      isAuthenticated: false,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue({ isSuccess: false, data: undefined });
    const { container } = render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(container.querySelector('nav')).not.toBeInTheDocument();
  });

  it('renders an Index nav link', () => {
    const { container } = renderNavBar();
    expect(
      within(desktopNav(container)).getByRole('link', { name: /^index$/i }),
    ).toBeInTheDocument();
  });

  it('points the Index link at /index', () => {
    const { container } = renderNavBar();
    expect(
      within(desktopNav(container)).getByRole('link', { name: /^index$/i }),
    ).toHaveAttribute('href', '/index');
  });

  it('marks the Index link active on the /index route', () => {
    const { container } = renderNavBarAt('/index');
    const indexLink = within(desktopNav(container)).getByRole('link', { name: /^index$/i });
    expect(indexLink).toHaveAttribute('aria-current', 'page');
  });

  it('does not mark the Index link active on the root route', () => {
    const { container } = renderNavBarAt('/');
    const nav = desktopNav(container);
    const searchLink = within(nav).getByRole('link', { name: /^search$/i });
    const indexLink = within(nav).getByRole('link', { name: /^index$/i });
    // On '/', Search is the active route — Index must not have aria-current.
    expect(searchLink).toHaveAttribute('aria-current', 'page');
    expect(indexLink).not.toHaveAttribute('aria-current');
  });

  // ── MAJOR 1: active link underline ────────────────────────────────────────

  it('applies the link-active CSS class to the active nav link', () => {
    const { container } = renderNavBarAt('/library');
    const nav = desktopNav(container);
    const libraryLink = within(nav).getByRole('link', { name: 'Library' });
    const searchLink = within(nav).getByRole('link', { name: /^search$/i });
    // CSS Modules transform class names; check that the active class differs
    // from the base class — the active link gets an extra class.
    expect(libraryLink.className).not.toEqual(searchLink.className);
  });

  // ── MAJOR 2: IndexStatusPill ──────────────────────────────────────────────

  it('shows the index-status pill when stats are available', () => {
    renderNavBar();
    // Pill is rendered in both desktop and mobile surfaces — first match suffices.
    expect(screen.getAllByLabelText(/index ready, 42 documents/i)[0]).toBeInTheDocument();
  });

  it('hides the index-status pill while stats are loading', () => {
    mockUseAuth.mockReturnValue({
      user: SAMPLE_USER,
      role: 'admin',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue({ isSuccess: false, data: undefined });
    render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(screen.queryByLabelText(/index ready/i)).not.toBeInTheDocument();
  });

  it('renders the document count in the status pill', () => {
    mockUseAuth.mockReturnValue({
      user: SAMPLE_USER,
      role: 'admin',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue(makeStats({ document_count: 1234 }));
    render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    expect(screen.getAllByLabelText(/index ready, 1,234 documents/i)[0]).toBeInTheDocument();
  });

  // ── MAJOR 3: Mobile surfaces ──────────────────────────────────────────────

  it('renders the mobile navigation landmark', () => {
    const { container } = renderNavBar();
    expect(
      container.querySelector('nav[aria-label="Mobile navigation"]'),
    ).toBeInTheDocument();
  });

  it('renders the mobile top bar banner', () => {
    const { container } = renderNavBar();
    expect(container.querySelector('[role="banner"]')).toBeInTheDocument();
  });

  it('renders four tabs in the bottom tab bar for an admin', () => {
    const { container } = renderNavBar();
    const mobileNav = container.querySelector('nav[aria-label="Mobile navigation"]');
    expect(mobileNav).not.toBeNull();
    expect(within(mobileNav as HTMLElement).getAllByRole('link')).toHaveLength(4);
  });

  it('renders three tabs in the bottom tab bar for a non-admin', () => {
    mockUseAuth.mockReturnValue({
      user: { ...SAMPLE_USER, role: 'member' },
      role: 'member',
      isAuthenticated: true,
      isLoading: false,
    });
    mockUseLogout.mockReturnValue(makeLogout());
    mockUseStats.mockReturnValue(makeStats());
    const { container } = render(
      <MemoryRouter>
        <AppNavBar />
      </MemoryRouter>,
    );
    const mobileNav = container.querySelector('nav[aria-label="Mobile navigation"]');
    expect(mobileNav).not.toBeNull();
    expect(within(mobileNav as HTMLElement).getAllByRole('link')).toHaveLength(3);
  });
});
