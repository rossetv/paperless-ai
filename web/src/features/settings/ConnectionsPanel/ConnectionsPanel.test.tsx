import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectionsPanel } from './ConnectionsPanel';
import type { SettingsSection } from '../fieldModel/types';
import { SETTINGS_SECTIONS } from '../fieldModel/sections';

// The 'connections' section from the actual model
const CONNECTIONS_SECTION = SETTINGS_SECTIONS.find(
  (s) => s.id === 'connections',
)! as SettingsSection;

// Real backend mask — matches SECRET_MASK in settings_routes.py.
const MASK = '********';

// Minimal draft values — just what's needed for credential checks
const DRAFT_OPENAI: Record<string, string> = {
  LLM_PROVIDER: 'openai',
  PAPERLESS_URL: 'http://paperless.lan:8000',
  PAPERLESS_PUBLIC_URL: 'http://paperless.lan:8000',
  PAPERLESS_TOKEN: MASK,
  OPENAI_API_KEY: MASK,
  OLLAMA_BASE_URL: '',
};

const DRAFT_OLLAMA: Record<string, string> = {
  ...DRAFT_OPENAI,
  LLM_PROVIDER: 'ollama',
  OLLAMA_BASE_URL: 'http://ollama.lan:11434/v1/',
};

const DRAFT_EMPTY_CREDS: Record<string, string> = {
  LLM_PROVIDER: 'openai',
  PAPERLESS_URL: '',
  PAPERLESS_PUBLIC_URL: '',
  PAPERLESS_TOKEN: '',
  OPENAI_API_KEY: '',
  OLLAMA_BASE_URL: '',
};

// Mock useTestConnection so no network calls happen.
// Individual tests can override the mock behaviour via vi.mocked().
const mockMutateAsync = vi.fn().mockResolvedValue({ ok: true, document_count: 42, detail: 'ok' });

vi.mock('../../../api/hooks/settings', () => ({
  useTestConnection: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false,
    isError: false,
    isSuccess: false,
  }),
}));

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function renderPanel(draft: Record<string, string> = DRAFT_OPENAI) {
  render(
    <ConnectionsPanel
      section={CONNECTIONS_SECTION}
      values={draft}
      onChange={() => undefined}
      reindexKeys={new Set()}
      defaultKeys={new Set()}
    />,
    { wrapper: makeWrapper() },
  );
}

describe('ConnectionsPanel', () => {
  afterEach(() => vi.clearAllMocks());

  it('always shows Paperless-ngx card header', () => {
    renderPanel();
    expect(screen.getByText('Paperless-ngx')).toBeInTheDocument();
  });

  it('always shows OpenAI card header', () => {
    renderPanel();
    // "OpenAI" appears in both the provider segmented strip and the card title.
    // We just check it's present in the accordion header by verifying the Test button exists.
    expect(screen.getByRole('button', { name: 'Test OpenAI' })).toBeInTheDocument();
  });

  it('hides Ollama card when provider is openai', () => {
    renderPanel(DRAFT_OPENAI);
    // "Ollama" appears in the provider strip; the accordion card should be absent.
    expect(screen.queryByRole('button', { name: 'Test Ollama' })).not.toBeInTheDocument();
  });

  it('shows Ollama card when provider is ollama', () => {
    renderPanel(DRAFT_OLLAMA);
    expect(screen.getByRole('button', { name: 'Test Ollama' })).toBeInTheDocument();
  });

  it('shows "Not configured" for a service with empty required credential', async () => {
    renderPanel(DRAFT_EMPTY_CREDS);
    await waitFor(() => {
      // Both Paperless and OpenAI have empty creds, expect at least one "Not configured"
      const notConfiguredElements = screen.getAllByText('Not configured');
      expect(notConfiguredElements.length).toBeGreaterThan(0);
    });
  });

  it('does NOT call mutateAsync for a service with empty required credential', async () => {
    mockMutateAsync.mockClear();

    renderPanel(DRAFT_EMPTY_CREDS);

    // Wait a short while to ensure auto-test would have fired
    await waitFor(() => {
      expect(screen.getByText('Paperless-ngx')).toBeInTheDocument();
    });

    // With all creds empty, no auto-test probes should have been called
    expect(mockMutateAsync).not.toHaveBeenCalled();
  });

  it('expanding a card reveals its fields', async () => {
    renderPanel(DRAFT_OPENAI);
    // The Paperless card should be collapsed; click header to expand
    const paperlessHeader = screen.getByRole('button', { name: 'Paperless-ngx' });
    await userEvent.click(paperlessHeader);
    // After expansion, the PAPERLESS_URL field should be visible (text label)
    expect(screen.getByText('Server URL')).toBeVisible();
  });

  it('renders the AI provider segmented strip', () => {
    renderPanel();
    // The LLM_PROVIDER segmented control should be visible
    expect(screen.getByRole('radiogroup', { name: /llm provider/i })).toBeInTheDocument();
  });

  it('renders the provider strip with OpenAI and Ollama options', () => {
    renderPanel();
    expect(screen.getByRole('radio', { name: 'OpenAI' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Ollama' })).toBeInTheDocument();
  });

  // ── Failure-path tests (FIX 2) ──────────────────────────────────────────────

  it('shows err tone + detail label when probe resolves ok:false', async () => {
    mockMutateAsync.mockResolvedValue({ ok: false, document_count: 0, detail: 'bad key' });
    renderPanel(DRAFT_OPENAI);
    await waitFor(() => {
      expect(screen.getByText('bad key')).toBeInTheDocument();
    });
  });

  it('shows err/"Error" state when probe throws', async () => {
    mockMutateAsync.mockRejectedValue(new Error('network failure'));
    renderPanel(DRAFT_OPENAI);
    await waitFor(() => {
      // Expect the Error label to appear at least once
      const errorLabels = screen.getAllByText('Error');
      expect(errorLabels.length).toBeGreaterThan(0);
    });
  });

  it('shows "Connected" (not a document count) when OpenAI probe resolves ok:true', async () => {
    // Use a draft with no Paperless URL so only the OpenAI probe fires.
    const onlyOpenAI = {
      ...DRAFT_OPENAI,
      PAPERLESS_URL: '',
      PAPERLESS_PUBLIC_URL: '',
      PAPERLESS_TOKEN: '',
    };
    mockMutateAsync.mockResolvedValue({ ok: true, document_count: 99, detail: 'ok' });
    renderPanel(onlyOpenAI);
    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument();
    });
    // OpenAI must never show a doc-count string — only Paperless shows that.
    expect(screen.queryByText('99 docs')).not.toBeInTheDocument();
  });

  // ── Masked-secret probe body (regression for FIX 1) ───────────────────────

  it('paperless probe sends paperless_token:"" when draft token is the server mask', async () => {
    mockMutateAsync.mockClear();
    mockMutateAsync.mockResolvedValue({ ok: true, document_count: 5, detail: 'ok' });

    // PAPERLESS_TOKEN is exactly the mask
    const draft = { ...DRAFT_OPENAI, PAPERLESS_TOKEN: MASK };
    renderPanel(draft);

    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalled());

    const paperlessCall = (mockMutateAsync.mock.calls as unknown[][]).find(
      (args) => (args[0] as { service: string }).service === 'paperless',
    );
    expect(paperlessCall).toBeDefined();
    expect((paperlessCall![0] as { paperless_token: string }).paperless_token).toBe('');
  });

  it('openai probe omits openai_api_key when draft key is the server mask', async () => {
    mockMutateAsync.mockClear();
    mockMutateAsync.mockResolvedValue({ ok: true, document_count: 0, detail: 'ok' });

    // OPENAI_API_KEY is exactly the mask; only OpenAI configured so only one probe fires.
    const draft = {
      LLM_PROVIDER: 'openai',
      PAPERLESS_URL: '',
      PAPERLESS_PUBLIC_URL: '',
      PAPERLESS_TOKEN: '',
      OPENAI_API_KEY: MASK,
      OLLAMA_BASE_URL: '',
    };
    renderPanel(draft);

    // Wait for the openai probe — it stagger-fires immediately (index=0 since paperless is skipped).
    await waitFor(
      () => {
        const openaiCall = (mockMutateAsync.mock.calls as unknown[][]).find(
          (args) => (args[0] as { service: string }).service === 'openai',
        );
        expect(openaiCall).toBeDefined();
        // The key must be absent — backend uses its stored value.
        expect(openaiCall![0]).not.toHaveProperty('openai_api_key');
      },
      { timeout: 1000 },
    );
  });

  // ── Ollama auto-probe on visibility (FIX 4) ───────────────────────────────

  it('auto-probes Ollama exactly once when provider switches from openai to ollama', async () => {
    mockMutateAsync.mockClear();
    mockMutateAsync.mockResolvedValue({ ok: true, document_count: 0, detail: 'ok' });

    const { rerender } = render(
      <ConnectionsPanel
        section={CONNECTIONS_SECTION}
        values={DRAFT_OPENAI}
        onChange={() => undefined}
        reindexKeys={new Set()}
        defaultKeys={new Set()}
      />,
      { wrapper: makeWrapper() },
    );

    // Let mount probes settle
    await waitFor(() => expect(mockMutateAsync).toHaveBeenCalled());
    const callsAfterMount = mockMutateAsync.mock.calls.length;

    // Switch to ollama
    rerender(
      <ConnectionsPanel
        section={CONNECTIONS_SECTION}
        values={DRAFT_OLLAMA}
        onChange={() => undefined}
        reindexKeys={new Set()}
        defaultKeys={new Set()}
      />,
    );

    await waitFor(() => {
      const ollamaCalls = (mockMutateAsync.mock.calls as unknown[][]).filter(
        (args) => (args[0] as { service: string }).service === 'ollama',
      );
      expect(ollamaCalls).toHaveLength(1);
    });

    // Total new calls = exactly 1 (ollama only; paperless + openai NOT re-probed)
    const newCalls = mockMutateAsync.mock.calls.length - callsAfterMount;
    expect(newCalls).toBe(1);
  });
});
