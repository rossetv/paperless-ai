import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { UseMutationResult } from '@tanstack/react-query';
import type { CreateApiKeyResponse } from '../../../api/types';
import { APIKeyCreatePanel } from './APIKeyCreatePanel';

vi.mock('../../../api/hooks', () => ({ useCreateApiKey: vi.fn() }));
import { useCreateApiKey } from '../../../api/hooks';
const mockCreate = useCreateApiKey as ReturnType<typeof vi.fn>;

const RESULT: CreateApiKeyResponse = {
  api_key: {
    id: 9,
    name: 'n8n',
    key_prefix: 'sk-pls-bQ94X',
    scopes: ['api'],
    owner_id: 1,
    owner_name: 'Alex Morgan',
    created_at: '2026-05-22T00:00:00Z',
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    request_count: 0,
  },
  secret: 'sk-pls-bQ94XfullSECRETvalue1234567890',
};

function stub(
  mutateAsync: () => Promise<CreateApiKeyResponse>,
  overrides: Partial<UseMutationResult<CreateApiKeyResponse, Error, never>> = {},
): UseMutationResult<CreateApiKeyResponse, Error, never> {
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
  } as UseMutationResult<CreateApiKeyResponse, Error, never>;
}

beforeEach(() => {
  mockCreate.mockReturnValue(stub(async () => RESULT));
  // jsdom has no real clipboard — stub writeText.
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe('APIKeyCreatePanel — form', () => {
  it('renders a create-key dialog', () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: /create api key/i })).toBeInTheDocument();
  });

  it('rejects an empty key name on submit', async () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    expect(screen.getByText(/give the key a name/i)).toBeInTheDocument();
  });

  it('rejects a submit with no scopes selected', async () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    // the API scope is on by default — turn it off
    await userEvent.click(screen.getByRole('checkbox', { name: /api/i }));
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    expect(screen.getByText(/select at least one scope/i)).toBeInTheDocument();
  });

  it('calls createApiKey with the form values on a valid submit', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(RESULT);
    mockCreate.mockReturnValue(stub(mutateAsync));
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledTimes(1));
    expect(mutateAsync.mock.calls[0]?.[0]).toMatchObject({
      name: 'n8n',
      scopes: ['api'],
      expires_at: null,
    });
  });
});

describe('APIKeyCreatePanel — one-time reveal', () => {
  it('shows the full secret after a successful mint', async () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    // Wait for the Modal focus-trap rAF to complete before interacting.
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() =>
      expect(screen.getByText('sk-pls-bQ94XfullSECRETvalue1234567890')).toBeInTheDocument(),
    );
  });

  it('hides the form fields once the secret is revealed', async () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() =>
      expect(screen.queryByLabelText(/key name/i)).not.toBeInTheDocument(),
    );
  });

  it('copies the secret to the clipboard when Copy is clicked', async () => {
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() => screen.getByRole('button', { name: /copy/i }));
    await userEvent.click(screen.getByRole('button', { name: /copy/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      'sk-pls-bQ94XfullSECRETvalue1234567890',
    );
  });

  it('calls onClose from the reveal panel Done button', async () => {
    const onClose = vi.fn();
    render(<APIKeyCreatePanel onClose={onClose} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() => screen.getByRole('button', { name: /done/i }));
    await userEvent.click(screen.getByRole('button', { name: /done/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('surfaces an error when the mint fails', async () => {
    mockCreate.mockReturnValue(stub(() => Promise.reject(new Error('boom'))));
    render(<APIKeyCreatePanel onClose={vi.fn()} />);
    await waitFor(() => expect(document.activeElement).not.toBe(document.body));
    await userEvent.type(screen.getByLabelText(/key name/i), 'n8n');
    await userEvent.click(screen.getByRole('button', { name: /generate key/i }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/could not create/i),
    );
  });
});
