import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsScreen } from './SettingsScreen';

// A complete settings payload — every key the field model references.
const SETTINGS = {
  PAPERLESS_URL: 'http://paperless.lan:8000',
  PAPERLESS_PUBLIC_URL: 'http://paperless.lan:8000',
  PAPERLESS_TOKEN: '********',
  LLM_PROVIDER: 'openai',
  OPENAI_API_KEY: '********',
  OLLAMA_BASE_URL: 'http://ollama.lan:11434/v1/',
  OCR_MODELS: ['gpt-5.4-mini', 'gpt-5.4'],
  OCR_REASONING_EFFORT: 'low',
  CLASSIFY_MODELS: ['gpt-5.4-mini', 'gpt-5.4'],
  CLASSIFY_REASONING_EFFORT: 'low',
  SEARCH_TOP_K: 10,
  SEARCH_MAX_REFINEMENTS: 1,
  SEARCH_PLANNER_MODEL: 'gpt-5.4-mini',
  SEARCH_PLANNER_REASONING_EFFORT: 'low',
  SEARCH_ANSWER_MODEL: 'gpt-5.4',
  SEARCH_ANSWER_REASONING_EFFORT: 'medium',
  SEARCH_JUDGE_MODEL: 'gpt-5.4-mini',
  SEARCH_JUDGE_REASONING_EFFORT: 'low',
  SEARCH_MAX_CONCURRENT: 4,
  SEARCH_SESSION_TTL: 604800,
  SEARCH_SERVER_HOST: '0.0.0.0',
  SEARCH_SERVER_PORT: 8080,
  SEARCH_GATE_JUDGE: true,
  SEARCH_IDENTITY_AWARE: true,
  SEARCH_JUDGE_RATIONALES: false,
  SEARCH_RELEVANCE_MIN_SIMILARITY: 0.6,
  SEARCH_RELEVANCE_TIER_STRONG: 0.7,
  SEARCH_RELEVANCE_TIER_GOOD: 0.66,
  SEARCH_RELEVANCE_TIER_PARTIAL: 0.6,
  EMBEDDING_PROVIDER: 'openai',
  EMBEDDING_MODEL: 'text-embedding-3-small',
  EMBEDDING_DIMENSIONS: 1536,
  EMBEDDING_MAX_CONCURRENT: 4,
  CHUNK_SIZE: 2000,
  CHUNK_OVERLAP: 256,
  RECONCILE_INTERVAL: 300,
  DELETION_SWEEP_INTERVAL: 3600,
  OCR_DPI: 300,
  OCR_MAX_SIDE: 1600,
  PAGE_WORKERS: 8,
  OCR_INCLUDE_PAGE_MODELS: false,
  OCR_REFUSAL_MARKERS: ['i cannot assist'],
  CLASSIFY_MAX_PAGES: 3,
  CLASSIFY_TAIL_PAGES: 2,
  CLASSIFY_TAG_LIMIT: 5,
  CLASSIFY_TAXONOMY_LIMIT: 100,
  CLASSIFY_MAX_CHARS: 0,
  CLASSIFY_MAX_TOKENS: 0,
  CLASSIFY_HEADERLESS_CHAR_LIMIT: 15000,
  CLASSIFY_DEFAULT_COUNTRY_TAG: 'Ireland',
  CLASSIFY_PERSON_FIELD_ID: 0,
  PRE_TAG_ID: 443,
  POST_TAG_ID: 444,
  OCR_PROCESSING_TAG_ID: 551,
  CLASSIFY_PRE_TAG_ID: 444,
  CLASSIFY_POST_TAG_ID: 0,
  CLASSIFY_PROCESSING_TAG_ID: 0,
  ERROR_TAG_ID: 552,
  DOCUMENT_WORKERS: 4,
  LLM_MAX_CONCURRENT: 0,
  POLL_INTERVAL: 15,
  REQUEST_TIMEOUT: 180,
  MAX_RETRIES: 20,
  MAX_RETRY_BACKOFF_SECONDS: 30,
  LOG_LEVEL: 'INFO',
  LOG_FORMAT: 'console',
};

const SECRET = new Set(['PAPERLESS_TOKEN', 'OPENAI_API_KEY']);
const REINDEX = new Set(['EMBEDDING_PROVIDER', 'EMBEDDING_MODEL', 'CHUNK_SIZE', 'CHUNK_OVERLAP']);

/**
 * Convert the flat typed map above into the wire shape `{ settings: [...] }`.
 */
function toSettingsBody(
  map: Record<string, unknown>,
  opts: { defaultKeys?: Set<string>; defaultValues?: Record<string, string> } = {},
): {
  settings: {
    key: string;
    value: string | null;
    source: string;
    is_secret: boolean;
    requires_reindex: boolean;
    default_value: string | null;
  }[];
} {
  return {
    settings: Object.entries(map).map(([key, v]) => {
      const isDefault = opts.defaultKeys?.has(key) ?? false;
      const rawValue = Array.isArray(v)
        ? v.join(', ')
        : typeof v === 'boolean'
          ? String(v)
          : String(v);
      return {
        key,
        value: isDefault ? null : rawValue,
        source: isDefault ? 'default' : 'database',
        is_secret: SECRET.has(key),
        requires_reindex: REINDEX.has(key),
        default_value: isDefault ? (opts.defaultValues?.[key] ?? rawValue) : null,
      };
    }),
  };
}

function mockResponse(r: { status: number; body: unknown }): object {
  const serialised = r.body !== null ? JSON.stringify(r.body) : '';
  return {
    ok: r.status >= 200 && r.status < 300,
    status: r.status,
    headers: new Headers(serialised ? { 'content-type': 'application/json' } : {}),
    text: () => Promise.resolve(serialised),
    json: () => Promise.resolve(r.body),
  };
}

function mockFetchSequence(responses: { status: number; body: unknown }[]): void {
  const fn = vi.fn();
  for (const r of responses) {
    fn.mockResolvedValueOnce(mockResponse(r));
  }
  const last = responses.at(-1);
  if (last !== undefined) {
    fn.mockResolvedValue(mockResponse(last));
  }
  vi.stubGlobal('fetch', fn);
}

function renderScreen(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/settings']}>
        <SettingsScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SettingsScreen', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows a loading placeholder before the fetch resolves', () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders the Settings title and all eight section headings', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Connections' });
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    for (const name of [
      'Connections',
      'AI providers',
      'OCR',
      'Classification',
      'Indexing',
      'Search',
      'Automation & Daemons',
      'Logging',
    ]) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
  });

  it('shows an error placeholder when the fetch fails', async () => {
    mockFetchSequence([{ status: 500, body: { detail: 'boom' } }]);
    renderScreen();
    expect(await screen.findByText(/could not load/i)).toBeInTheDocument();
  });

  it('binds a field to its fetched value', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    expect(await screen.findByRole('spinbutton', { name: 'Top K' })).toHaveValue(10);
  });

  it('shows no unsaved-changes count and a hidden SaveBar initially', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Connections' });
    // The SaveBar is always in the DOM but hidden via aria-hidden + CSS transform
    // when there are no dirty fields.
    const message = screen.queryByText(/unsaved change/i);
    if (message !== null) {
      expect(message.closest('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('shows an unsaved-changes count in the SaveBar after an edit', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    expect(screen.getByText(/1 unsaved change/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save changes/i })).toBeEnabled();
  });

  it('Discard reverts every edit', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const topK = await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(topK).toHaveValue(10);
    // After discard the SaveBar is hidden (aria-hidden) — not removed from DOM.
    const message = screen.queryByText(/unsaved change/i);
    if (message !== null) {
      expect(message.closest('[aria-hidden="true"]')).not.toBeNull();
    }
  });

  it('Save PUTs only the changed keys, as a string changes map', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
      const put = calls.find((c) => (c[1] as RequestInit).method === 'PUT');
      expect(put).toBeDefined();
      expect(JSON.parse((put![1] as RequestInit).body as string)).toEqual({
        changes: { SEARCH_TOP_K: '11' },
      });
    });
  });

  it('clears the unsaved count after a successful save', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    // After a successful save the SaveBar slides back out (aria-hidden).
    await waitFor(() => {
      const message = screen.queryByText(/unsaved change/i);
      if (message !== null) {
        expect(message.closest('[aria-hidden="true"]')).not.toBeNull();
      }
    });
  });

  it('shows a re-indexing toast when the save response flags reindex_triggered', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      {
        status: 200,
        body: {
          ...toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }),
          reindex_triggered: true,
        },
      },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    // The server forced a rebuild; the screen surfaces a re-indexing toast.
    // Match the toast-unique phrase, not the per-field "requires re-indexing"
    // notes that are always present for the re-index keys.
    expect(
      await screen.findByText(/re-embedding your library/i),
    ).toBeInTheDocument();
  });

  it('shows no re-indexing toast when the save does not trigger one', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      {
        status: 200,
        body: {
          ...toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }),
          reindex_triggered: false,
        },
      },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => {
      const put = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
        (c) => (c[1] as RequestInit).method === 'PUT',
      );
      expect(put).toBeDefined();
    });
    expect(screen.queryByText(/re-embedding your library/i)).toBeNull();
  });

  it('renders the Connections section as accordion cards (Paperless-ngx, OpenAI, Ollama)', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Connections' });
    // The ConnectionsPanel renders accordion cards — each has a Test button.
    // All three services are always shown now, independent of LLM_PROVIDER.
    expect(screen.getByRole('button', { name: 'Test Paperless-ngx' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test OpenAI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test Ollama' })).toBeInTheDocument();
  });

  it('renders the AI providers section with two "Provider" radiogroups inside their respective cards', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // Wait for the section to appear.
    await screen.findByRole('heading', { level: 2, name: 'AI providers' });
    // The group titles are h3s; the radiogroups are labelled by the field label
    // "Provider" (not the group title). There are exactly two "Provider" radiogroups
    // inside the AI providers region.
    const providersRegion = screen.getByRole('region', { name: 'AI providers' });
    // The 'Chat & vision' and 'Embeddings' group titles are rendered as h3s within the region.
    // There are two h3s named 'Embeddings' across the full page (AI providers + Indexing),
    // so scope the query to the providers region.
    const { getAllByRole: getAllByRoleInRegion } = within(providersRegion);
    expect(getAllByRoleInRegion('heading', { level: 3, name: 'Chat & vision' })).toHaveLength(1);
    expect(getAllByRoleInRegion('heading', { level: 3, name: 'Embeddings' })).toHaveLength(1);
    // Both field controls are segmented radiogroups, each labelled "Provider".
    const providerGroups = Array.from(
      providersRegion.querySelectorAll('[role="radiogroup"][aria-label="Provider"]'),
    );
    expect(providerGroups).toHaveLength(2);
  });

  it('cross-section conditional: EMBEDDING_PROVIDER=openai renders a combobox for Embedding model', async () => {
    // SETTINGS seeds EMBEDDING_PROVIDER='openai', so the conditional control in
    // the Indexing section should resolve to the select variant.
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Indexing' });
    expect(screen.getByRole('combobox', { name: 'Embedding model' })).toBeInTheDocument();
  });

  it('cross-section conditional: EMBEDDING_PROVIDER=ollama renders a textbox for Embedding model', async () => {
    // Override EMBEDDING_PROVIDER to 'ollama'; the conditional control in Indexing
    // must fall back to the free-text variant because EMBEDDING_PROVIDER lives in
    // the 'providers' section and shares the same draft.
    const ollamaSettings = { ...SETTINGS, EMBEDDING_PROVIDER: 'ollama' };
    mockFetchSequence([{ status: 200, body: toSettingsBody(ollamaSettings) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Indexing' });
    expect(screen.getByRole('textbox', { name: 'Embedding model' })).toBeInTheDocument();
  });

  it('reindex pill is present inside the AI providers region for the Embeddings card', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // Wait for the section.
    const providersRegion = await screen.findByRole('region', { name: 'AI providers' });
    // The Embeddings group card (h3 'Embeddings') is inside the providers region.
    // EMBEDDING_PROVIDER has requires_reindex=true, so the amber pill must appear
    // within the providers region.
    const pills = Array.from(providersRegion.querySelectorAll('*')).filter(
      (el) => el.textContent?.match(/rebuilds the index on save/i),
    );
    expect(pills.length).toBeGreaterThan(0);
  });

  it('shows a reindex pill on a re-index key', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const pills = await screen.findAllByText(/rebuilds the index on save/i);
    expect(pills.length).toBeGreaterThan(0);
  });

  it('shows the coded default value in the control when source is default', async () => {
    mockFetchSequence([
      {
        status: 200,
        body: toSettingsBody(SETTINGS, {
          defaultKeys: new Set(['SEARCH_TOP_K']),
          defaultValues: { SEARCH_TOP_K: '10' },
        }),
      },
    ]);
    renderScreen();
    expect(await screen.findByRole('spinbutton', { name: 'Top K' })).toHaveValue(10);
  });

  it('shows a default badge on a key whose source is default', async () => {
    mockFetchSequence([
      {
        status: 200,
        body: toSettingsBody(SETTINGS, {
          defaultKeys: new Set(['SEARCH_TOP_K']),
          defaultValues: { SEARCH_TOP_K: '10' },
        }),
      },
    ]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Search' });
    expect(screen.getByText('default')).toBeInTheDocument();
  });

  it('shows the rebuild warning in SaveBar when a reindex key is edited', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // Wait for the Indexing section to render, then click Increase on Chunk size
    await screen.findByRole('spinbutton', { name: 'Chunk size' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Chunk size' }));
    // The SaveBar uses aria-live="polite" on the outer div; scope the assertion
    // inside it to avoid matching static reindex pills or hints elsewhere.
    const saveBar = document.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(saveBar).not.toBeNull();
    expect(saveBar.textContent).toMatch(/rebuild|re-embed/i);
  });

  it('shows the normal "no restart" caption when only a non-reindex key is edited', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    // Scope to the SaveBar to avoid matching the SettingsLayout subtitle.
    const saveBar = document.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(saveBar).not.toBeNull();
    expect(saveBar.textContent).toMatch(/no restart/i);
  });
});
