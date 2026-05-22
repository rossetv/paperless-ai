import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { ApiKey, ApiKeyEnvelope, UpdateApiKeyRequest } from '../../../api/types';
import { APIKeyEditPanel } from './APIKeyEditPanel';

vi.mock('../../../api/hooks', () => ({ useUpdateApiKey: vi.fn() }));
import { useUpdateApiKey } from '../../../api/hooks';
const mockUpdate = useUpdateApiKey as ReturnType<typeof vi.fn>;

const KEY: ApiKey = {
  id: 7,
  name: 'CI token',
  key_prefix: 'sk-pls-aF82C',
  scopes: ['api'],
  owner_id: 1,
  owner_name: 'Alex Morgan',
  created_at: '2026-01-12T00:00:00Z',
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  request_count: 12,
};

/** A key that already has an expiry set (30 days from a fixed timestamp). */
const KEY_WITH_EXPIRY: ApiKey = {
  ...KEY,
  id: 8,
  expires_at: '2026-06-22T00:00:00Z',
};

const RESULT: ApiKeyEnvelope = { api_key: { ...KEY, name: 'CI renamed' } };

function stub(
  mutateAsync: (vars: { id: number; body: UpdateApiKeyRequest }) => Promise<ApiKeyEnvelope>,
): UseMutationResult<ApiKeyEnvelope, Error, { id: number; body: UpdateApiKeyRequest }> {
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
  } as UseMutationResult<ApiKeyEnvelope, Error, { id: number; body: UpdateApiKeyRequest }>;
}

beforeEach(() => {
  mockUpdate.mockReturnValue(stub(async () => RESULT));
});

describe('APIKeyEditPanel', () => {
  it('renders an edit-key dialog pre-filled with the key name', () => {
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: /edit api key/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/key name/i)).toHaveValue('CI token');
  });

  it("pre-checks the key's current scopes", () => {
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: /api/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /mcp/i })).not.toBeChecked();
  });

  it('rejects clearing the key name', async () => {
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    await userEvent.clear(screen.getByLabelText(/key name/i));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    expect(screen.getByText(/give the key a name/i)).toBeInTheDocument();
  });

  it('rejects a submit with no scopes selected', async () => {
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    // `api` is the only checked scope — turn it off.
    await userEvent.click(screen.getByRole('checkbox', { name: /api/i }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    expect(screen.getByText(/select at least one scope/i)).toBeInTheDocument();
  });

  it('calls updateApiKey with the key id and edited fields, omitting expires_at when not touched', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(RESULT);
    mockUpdate.mockReturnValue(stub(mutateAsync));
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    // Wait for the Modal focus-trap rAF to complete before interacting.
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.clear(screen.getByLabelText(/key name/i));
    await userEvent.type(screen.getByLabelText(/key name/i), 'CI renamed');
    await userEvent.click(screen.getByRole('checkbox', { name: /mcp/i }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    // expires_at must be absent from the body — the user did not touch the chip.
    expect(mutateAsync.mock.calls[0]?.[0]).toEqual({
      id: 7,
      body: { name: 'CI renamed', scopes: ['api', 'mcp'] },
    });
  });

  it('preserves an existing expiry when the user renames without touching the chip', async () => {
    // MAJOR-2 regression: saving a rename must not silently clear an existing
    // expires_at because the form initialises expiryDays to null.
    const mutateAsync = vi.fn().mockResolvedValue({ api_key: KEY_WITH_EXPIRY });
    mockUpdate.mockReturnValue(stub(mutateAsync));
    render(<APIKeyEditPanel apiKey={KEY_WITH_EXPIRY} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.clear(screen.getByLabelText(/key name/i));
    await userEvent.type(screen.getByLabelText(/key name/i), 'CI renamed');
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const body = mutateAsync.mock.calls[0]?.[0]?.body as Record<string, unknown>;
    // expires_at must be absent — leaving the server-side value unchanged.
    expect(body).not.toHaveProperty('expires_at');
  });

  it('includes expires_at in the body when the user explicitly picks a chip', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ api_key: KEY_WITH_EXPIRY });
    mockUpdate.mockReturnValue(stub(mutateAsync));
    render(<APIKeyEditPanel apiKey={KEY_WITH_EXPIRY} onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    // Explicitly select "Never" — should now include expires_at: null.
    await userEvent.click(screen.getByRole('button', { name: /never/i }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    const body = mutateAsync.mock.calls[0]?.[0]?.body as Record<string, unknown>;
    expect(body).toHaveProperty('expires_at', null);
  });

  it('closes the panel after a successful save', async () => {
    const onClose = vi.fn();
    render(<APIKeyEditPanel apiKey={KEY} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('surfaces an error when the save fails', async () => {
    mockUpdate.mockReturnValue(stub(() => Promise.reject(new Error('boom'))));
    render(<APIKeyEditPanel apiKey={KEY} onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not save/i),
    );
  });

  it('calls onClose from the Cancel button', async () => {
    const onClose = vi.fn();
    render(<APIKeyEditPanel apiKey={KEY} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
