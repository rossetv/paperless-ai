import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import type { ApiKeysResponse, ApiKey } from '../../../api/types';
import { APIKeysScreen } from './APIKeysScreen';

vi.mock('../../../api/hooks', () => ({
  useApiKeys: vi.fn(),
  useDeleteApiKey: vi.fn(),
}));
// useAuth tells the screen which keys the caller owns (Edit is owner-only).
vi.mock('../../../hooks/useAuth', () => ({ useAuth: vi.fn() }));
// Stub the create panel — it is unit-tested separately.
vi.mock('../APIKeyCreatePanel/APIKeyCreatePanel', () => ({
  APIKeyCreatePanel: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="key-panel">
      <button type="button" onClick={onClose}>
        close-panel
      </button>
    </div>
  ),
}));
// Stub the edit panel — it is unit-tested separately.
vi.mock('../APIKeyEditPanel/APIKeyEditPanel', () => ({
  APIKeyEditPanel: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="key-edit-panel">
      <button type="button" onClick={onClose}>
        close-edit
      </button>
    </div>
  ),
}));

import { useApiKeys, useDeleteApiKey } from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';
const mockKeys = useApiKeys as ReturnType<typeof vi.fn>;
const mockDelete = useDeleteApiKey as ReturnType<typeof vi.fn>;
const mockAuth = useAuth as ReturnType<typeof vi.fn>;

// A key that is active, one already expired.
const KEYS: ApiKey[] = [
  {
    id: 1,
    name: 'Claude · MCP integration',
    key_prefix: 'sk-pls-aF82C',
    scopes: ['mcp', 'api'],
    owner_id: 1,
    owner_name: 'Alex Morgan',
    created_at: '2026-01-12T00:00:00Z',
    expires_at: null,
    last_used_at: '2026-05-22T09:00:00Z',
    revoked_at: null,
    request_count: 184602,
  },
  {
    id: 4,
    name: 'Legacy CRON script',
    key_prefix: 'sk-pls-dE03P',
    scopes: ['api'],
    owner_id: 1,
    owner_name: 'Alex Morgan',
    created_at: '2024-08-11T00:00:00Z',
    expires_at: '2020-01-01T00:00:00Z',
    last_used_at: '2024-09-01T00:00:00Z',
    revoked_at: null,
    request_count: 203,
  },
];

function keysResult(
  overrides: Partial<UseQueryResult<ApiKeysResponse, Error>>,
): UseQueryResult<ApiKeysResponse, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<ApiKeysResponse, Error>;
}

function stubDelete(
  mutateAsync: (id: number) => Promise<void> = vi.fn().mockResolvedValue(undefined),
): UseMutationResult<void, Error, number> {
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
  } as UseMutationResult<void, Error, number>;
}

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={['/settings/keys']}>
      <APIKeysScreen />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockDelete.mockReturnValue(stubDelete());
  // The signed-in caller owns both keys in KEYS (owner_id 1) by default.
  mockAuth.mockReturnValue({
    user: {
      id: 1,
      username: 'alex.morgan',
      display_name: 'Alex Morgan',
      email: 'alex@home.lan',
      role: 'admin',
      status: 'active',
      created_at: '2024-09-12T00:00:00Z',
      last_login_at: null,
    },
  });
});

describe('APIKeysScreen', () => {
  it('shows a loading status while keys load', () => {
    mockKeys.mockReturnValue(keysResult({ isLoading: true, isPending: true }));
    renderScreen();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an error message when the keys query fails', () => {
    mockKeys.mockReturnValue(keysResult({ isError: true, error: new Error('x') }));
    renderScreen();
    expect(screen.getByText(/could not load/i)).toBeInTheDocument();
  });

  it('renders the API Keys page title', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    expect(screen.getByRole('heading', { level: 1, name: 'API Keys' })).toBeInTheDocument();
  });

  it('renders a row per key with its name and prefix', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    expect(screen.getByText('Claude · MCP integration')).toBeInTheDocument();
    expect(screen.getByText(/sk-pls-aF82C/)).toBeInTheDocument();
  });

  it('shows "Never" for a key with no expiry', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    expect(screen.getByText(/never/i)).toBeInTheDocument();
  });

  it('labels an already-expired key as expired', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    expect(screen.getAllByText(/expired/i).length).toBeGreaterThan(0);
  });

  it('opens the create panel from "New API key"', async () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /new api key/i }));
    expect(screen.getByTestId('key-panel')).toBeInTheDocument();
  });

  it('closes the create panel when it asks to close', async () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: /new api key/i }));
    await userEvent.click(screen.getByRole('button', { name: 'close-panel' }));
    await waitFor(() =>
      expect(screen.queryByTestId('key-panel')).not.toBeInTheDocument(),
    );
  });

  it('revokes an active key after confirming', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(undefined);
    mockDelete.mockReturnValue(stubDelete(mutateAsync));
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const activeRow = screen
      .getByText('Claude · MCP integration')
      .closest('tr') as HTMLElement;
    await userEvent.click(within(activeRow).getByRole('button', { name: /revoke/i }));
    await userEvent.click(within(activeRow).getByRole('button', { name: /confirm/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith(1));
  });

  it('offers Delete (not Revoke) for an already-expired key', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const expiredRow = screen
      .getByText('Legacy CRON script')
      .closest('tr') as HTMLElement;
    expect(within(expiredRow).getByRole('button', { name: /delete/i })).toBeInTheDocument();
    expect(within(expiredRow).queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument();
  });

  it('offers Edit on an active key the caller owns', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const activeRow = screen
      .getByText('Claude · MCP integration')
      .closest('tr') as HTMLElement;
    expect(within(activeRow).getByRole('button', { name: /edit/i })).toBeInTheDocument();
  });

  it('hides Edit on an expired key', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const expiredRow = screen
      .getByText('Legacy CRON script')
      .closest('tr') as HTMLElement;
    expect(within(expiredRow).queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
  });

  it('hides Edit on a key the caller does not own', () => {
    // The signed-in caller is user 1; this key is owned by user 2.
    const othersKey: ApiKey = { ...KEYS[0]!, id: 9, owner_id: 2, owner_name: 'Sam Patel' };
    mockKeys.mockReturnValue(
      keysResult({ isSuccess: true, data: { keys: [othersKey] } }),
    );
    renderScreen();
    const row = screen
      .getByText('Claude · MCP integration')
      .closest('tr') as HTMLElement;
    expect(within(row).queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
  });

  it('opens the edit panel when a row Edit is clicked', async () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const activeRow = screen
      .getByText('Claude · MCP integration')
      .closest('tr') as HTMLElement;
    await userEvent.click(within(activeRow).getByRole('button', { name: /edit/i }));
    expect(screen.getByTestId('key-edit-panel')).toBeInTheDocument();
  });

  it('closes the edit panel when it asks to close', async () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: KEYS } }));
    renderScreen();
    const activeRow = screen
      .getByText('Claude · MCP integration')
      .closest('tr') as HTMLElement;
    await userEvent.click(within(activeRow).getByRole('button', { name: /edit/i }));
    await userEvent.click(screen.getByRole('button', { name: 'close-edit' }));
    await waitFor(() =>
      expect(screen.queryByTestId('key-edit-panel')).not.toBeInTheDocument(),
    );
  });

  it('renders an empty message when there are no keys', () => {
    mockKeys.mockReturnValue(keysResult({ isSuccess: true, data: { keys: [] } }));
    renderScreen();
    expect(screen.getByText(/no api keys/i)).toBeInTheDocument();
  });
});
