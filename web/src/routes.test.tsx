import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseQueryResult } from '@tanstack/react-query';
import type { SetupStatus, MeResponse } from './api/types';
import { AppRoutes } from './routes';

// Leaf pages are mocked so routing is tested in isolation.
vi.mock('./pages/LoginPage', () => ({
  LoginPage: () => React.createElement('div', { 'data-testid': 'login-page' }, 'Login'),
}));
vi.mock('./pages/SearchPage', () => ({
  SearchPage: () => React.createElement('div', { 'data-testid': 'search-page' }, 'Search'),
}));
vi.mock('./pages/SetupPage', () => ({
  SetupPage: () => React.createElement('div', { 'data-testid': 'setup-page' }, 'Setup'),
}));
vi.mock('./pages/UsersPage', () => ({
  UsersPage: () => React.createElement('div', { 'data-testid': 'users-page' }, 'Users'),
}));
vi.mock('./pages/KeysPage', () => ({
  KeysPage: () => React.createElement('div', { 'data-testid': 'keys-page' }, 'Keys'),
}));
vi.mock('./pages/SettingsPage', () => ({
  SettingsPage: () => React.createElement('div', { 'data-testid': 'settings-page' }, 'Settings'),
}));
vi.mock('./pages/LibraryPage', () => ({
  LibraryPage: () => React.createElement('div', { 'data-testid': 'library-page' }, React.createElement('h1', null, 'Library')),
}));
vi.mock('./pages/IndexPage', () => ({
  IndexPage: () => React.createElement('div', { 'data-testid': 'index-page' }, React.createElement('h1', null, 'Index')),
}));
vi.mock('./pages/LibraryDocumentPage', () => ({
  LibraryDocumentPage: () =>
    React.createElement('div', { 'data-testid': 'library-document-page' }, 'LibraryDocument'),
}));
vi.mock('./pages/DocumentPage', () => ({
  DocumentPage: () =>
    React.createElement('div', { 'data-testid': 'document-page' }, 'Document'),
}));

vi.mock('./api/hooks', () => ({
  useSetupStatus: vi.fn(),
  useMe: vi.fn(),
}));

import { useSetupStatus, useMe } from './api/hooks';
const mockUseSetupStatus = useSetupStatus as ReturnType<typeof vi.fn>;
const mockUseMe = useMe as ReturnType<typeof vi.fn>;

function setupStatusResult(
  overrides: Partial<UseQueryResult<SetupStatus, Error>>,
): UseQueryResult<SetupStatus, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<SetupStatus, Error>;
}

function meResult(
  overrides: Partial<UseQueryResult<MeResponse, Error>>,
): UseQueryResult<MeResponse, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<MeResponse, Error>;
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

function Where(): React.ReactElement {
  const { pathname, search, hash } = useLocation();
  return <span data-testid="where">{pathname + search + hash}</span>;
}

function Nav(): React.ReactElement {
  const navigate = useNavigate();
  return (
    <>
      <button onClick={() => navigate('/library')}>to library</button>
      <button onClick={() => navigate('/library?q=tax')}>to library search</button>
      <button onClick={() => navigate('/index')}>to index</button>
      <button onClick={() => navigate('/')}>to root</button>
    </>
  );
}

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function routerTree(entry: string | { pathname: string; state: unknown }) {
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[entry]}>
        <AppRoutes />
        <Where />
        <Nav />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderAt(entry: string | { pathname: string; state: unknown }) {
  return render(routerTree(entry));
}

describe('AppRoutes', () => {
  it('shows a loading state while setup-status is resolving', () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isLoading: true, isPending: true }));
    mockUseMe.mockReturnValue(meResult({}));
    renderAt('/');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('routes to /setup when first-run setup is needed', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: true } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('setup-page')).toBeInTheDocument());
  });

  it('routes to /login when setup is done but the user is unauthenticated', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the search page when the user is authenticated', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects an authenticated user away from /login to the app', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/login');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('returns to the page asked for once the user has signed in', async () => {
    const setup = setupStatusResult({ isSuccess: true, data: { needed: false } });
    mockUseSetupStatus.mockReturnValue(setup);
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    const view = renderAt('/library?tag=tax#top');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());

    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    view.rerender(routerTree('/library?tag=tax#top'));
    await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
    expect(screen.getByTestId('where')).toHaveTextContent('/library?tag=tax#top');
  });

  it.each(['//evil.example/x', 'https://evil.example/x', '/login', 'library', 42, undefined])(
    'sends a signed-in user from /login to the root when the return target is %s',
    async (from) => {
      mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
      mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
      renderAt({ pathname: '/login', state: { from } });
      await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
    },
  );

  it('ignores a return target given in the query string', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/login?from=/library');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects to /setup from /login when setup is still needed', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: true } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/login');
    await waitFor(() => expect(screen.getByTestId('setup-page')).toBeInTheDocument());
  });

  it('redirects away from /setup once setup is complete', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/setup');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the users page for an admin at /settings/users', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings/users');
    await waitFor(() => expect(screen.getByTestId('users-page')).toBeInTheDocument());
  });

  it('renders the keys page for an admin at /settings/keys', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings/keys');
    await waitFor(() => expect(screen.getByTestId('keys-page')).toBeInTheDocument());
  });

  it('redirects a non-admin away from /settings/users to the app', async () => {
    const member = { ...SAMPLE_USER, role: 'member' as const };
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: member } }));
    renderAt('/settings/users');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated visitor from /settings/keys to /login', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/settings/keys');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the settings page for an admin at /settings', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings');
    await waitFor(() => expect(screen.getByTestId('settings-page')).toBeInTheDocument());
  });

  it('redirects a non-admin away from /settings to the app', async () => {
    const member = { ...SAMPLE_USER, role: 'member' as const };
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: member } }));
    renderAt('/settings');
    await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated visitor from /settings to /login', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/settings');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('redirects an unknown /settings/* path to the settings page, not the search home', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/settings/api-keys');
    await waitFor(() => expect(screen.getByTestId('settings-page')).toBeInTheDocument());
  });

  it('renders LibraryPage for an authenticated user at /library', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/library');
    await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated user away from /library', async () => {
    mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/library');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders the index page for an authenticated user at /index', async () => {
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/index');
    await waitFor(() => expect(screen.getByTestId('index-page')).toBeInTheDocument());
  });

  it('renders the index page for a non-admin too', async () => {
    const member = { ...SAMPLE_USER, role: 'member' as const };
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: member } }));
    renderAt('/index');
    await waitFor(() => expect(screen.getByTestId('index-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated visitor from /index to /login', async () => {
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/index');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  it('renders LibraryDocumentPage for an authenticated user at /library/document/42', async () => {
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/library/document/42');
    await waitFor(() =>
      expect(screen.getByTestId('library-document-page')).toBeInTheDocument(),
    );
  });

  it('renders DocumentPage for an authenticated user at /document/42', async () => {
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
    renderAt('/document/42');
    await waitFor(() => expect(screen.getByTestId('document-page')).toBeInTheDocument());
  });

  it('redirects an unauthenticated visitor from /document/42 to /login', async () => {
    mockUseSetupStatus.mockReturnValue(
      setupStatusResult({ isSuccess: true, data: { needed: false } }),
    );
    mockUseMe.mockReturnValue(meResult({ isError: true, error: new Error('Unauthenticated') }));
    renderAt('/document/42');
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument());
  });

  describe('page title and focus', () => {
    beforeEach(() => {
      mockUseSetupStatus.mockReturnValue(setupStatusResult({ isSuccess: true, data: { needed: false } }));
      mockUseMe.mockReturnValue(meResult({ isSuccess: true, data: { user: SAMPLE_USER } }));
      document.title = 'Paperless AI Search';
    });

    it('titles each page after its name and leaves focus alone on first load', async () => {
      renderAt('/library');
      await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
      expect(document.title).toBe('Library · Paperless AI Search');
      expect(document.body).toHaveFocus();
    });

    it('moves focus to the page heading when the pathname changes', async () => {
      renderAt('/library');
      await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'to index' }));
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Index' })).toHaveFocus());
      expect(document.title).toBe('Index · Paperless AI Search');
    });

    it('falls back to the content area when a page has no heading or main', async () => {
      renderAt('/library');
      await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
      await userEvent.click(screen.getByRole('button', { name: 'to root' }));
      await waitFor(() => expect(screen.getByTestId('search-page')).toBeInTheDocument());
      expect(screen.getByTestId('search-page').parentElement).toHaveFocus();
    });

    it('keeps focus where it is when only the query string changes', async () => {
      renderAt('/library');
      await waitFor(() => expect(screen.getByTestId('library-page')).toBeInTheDocument());
      const button = screen.getByRole('button', { name: 'to library search' });
      await userEvent.click(button);
      await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/library?q=tax'));
      expect(button).toHaveFocus();
    });
  });
});
