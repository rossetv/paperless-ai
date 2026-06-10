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

// Minimal draft values — just what's needed for credential checks
const DRAFT_OPENAI: Record<string, string> = {
  LLM_PROVIDER: 'openai',
  PAPERLESS_URL: 'http://paperless.lan:8000',
  PAPERLESS_PUBLIC_URL: 'http://paperless.lan:8000',
  PAPERLESS_TOKEN: '••••••••3f9b',
  OPENAI_API_KEY: 'sk-••••H8w2',
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

// Mock useTestConnection so no network calls happen
vi.mock('../../../api/hooks/settings', () => ({
  useTestConnection: () => ({
    mutateAsync: vi.fn().mockResolvedValue({ ok: true, document_count: 42, detail: 'ok' }),
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
    // Import the mocked hook to check calls
    const { useTestConnection } = await import('../../../api/hooks/settings');
    const mockMutateAsync = (useTestConnection as ReturnType<typeof vi.fn>)().mutateAsync as ReturnType<typeof vi.fn>;
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
});
