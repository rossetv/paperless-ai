import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsScreen } from './SettingsScreen';

// A complete settings payload — every key the field model references.
const SETTINGS = {
  PAPERLESS_URL: 'http://paperless.lan:8000',
  PAPERLESS_PUBLIC_URL: 'http://paperless.lan:8000',
  PAPERLESS_TOKEN: '••••••••3f9b',
  LLM_PROVIDER: 'openai',
  OPENAI_API_KEY: 'sk-••••H8w2',
  OLLAMA_BASE_URL: 'http://ollama.lan:11434/v1/',
  AI_MODELS: ['gpt-5.4-mini', 'gpt-5.4'],
  SEARCH_TOP_K: 10,
  SEARCH_MAX_REFINEMENTS: 1,
  SEARCH_PLANNER_MODEL: 'gpt-5.4-mini',
  SEARCH_ANSWER_MODEL: 'gpt-5.4',
  SEARCH_MAX_CONCURRENT: 4,
  SEARCH_SESSION_TTL: 604800,
  SEARCH_SERVER_HOST: '0.0.0.0',
  SEARCH_SERVER_PORT: 8080,
  EMBEDDING_MODEL: 'text-embedding-3-small',
  EMBEDDING_DIMENSIONS: 1536,
  EMBEDDING_MAX_CONCURRENT: 4,
  CHUNK_SIZE: 2000,
  CHUNK_OVERLAP: 256,
  RECONCILE_INTERVAL: 300,
  DELETION_SWEEP_INTERVAL: 3600,
  OCR_DPI: 300,
  OCR_MAX_SIDE: 1600,
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
  PAGE_WORKERS: 8,
  LLM_MAX_CONCURRENT: 0,
  POLL_INTERVAL: 15,
  REQUEST_TIMEOUT: 180,
  MAX_RETRIES: 20,
  MAX_RETRY_BACKOFF_SECONDS: 30,
  LOG_LEVEL: 'INFO',
  LOG_FORMAT: 'console',
};

const SECRET = new Set(['PAPERLESS_TOKEN', 'OPENAI_API_KEY']);
const REINDEX = new Set(['EMBEDDING_MODEL', 'CHUNK_SIZE', 'CHUNK_OVERLAP']);

/**
 * Convert the flat typed map above into the wire shape `{ settings: [...] }`.
 *
 * The backend returns one item per key with a STRING `value` — a list joins
 * with `, `, a boolean becomes `'true'`/`'false'`, a number is stringified.
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

/** Build a single mock Response-like object compatible with the fetch client. */
function mockResponse(r: { status: number; body: unknown }): object {
  // The API client reads `response.text()` then JSON.parses it — it does NOT
  // call `response.json()`. The headers check for `content-length: 0` to
  // short-circuit empty responses.
  const serialised = r.body !== null ? JSON.stringify(r.body) : '';
  return {
    ok: r.status >= 200 && r.status < 300,
    status: r.status,
    headers: new Headers(serialised ? { 'content-type': 'application/json' } : {}),
    text: () => Promise.resolve(serialised),
    json: () => Promise.resolve(r.body),
  };
}

/** Queue fetch responses in call order: GET settings, then any PUT. */
function mockFetchSequence(responses: { status: number; body: unknown }[]): void {
  const fn = vi.fn();
  for (const r of responses) {
    fn.mockResolvedValueOnce(mockResponse(r));
  }
  // Any further calls repeat the last response. Guard against empty array
  // (which callers never pass, but noUncheckedIndexedAccess requires it).
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

  it('renders the Settings title and all nine section headings', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // Wait for data to arrive by waiting for the first section heading — the
    // h1 "Settings" appears even in the loading placeholder, so we must wait
    // for a section-level h2 before asserting the rest synchronously.
    await screen.findByRole('heading', { level: 2, name: 'Paperless Connection' });
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    for (const name of [
      'Paperless Connection',
      'LLM Provider',
      'Search Server',
      'Embeddings & Index',
      'OCR',
      'Classification',
      'Pipeline Tags',
      'Performance',
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

  it('shows no unsaved-changes count and a disabled Save button initially', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // Wait for data to load — the Save button is only present in the loaded
    // state, not the loading placeholder.
    await screen.findByRole('heading', { level: 2, name: 'Paperless Connection' });
    expect(screen.queryByText(/unsaved change/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
  });

  it('shows an unsaved-changes count after an edit and enables Save', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const topK = await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    expect(topK).toHaveValue(11);
    expect(screen.getByText(/1 unsaved change/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
  });

  it('Discard reverts every edit', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const topK = await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(topK).toHaveValue(10);
    expect(screen.queryByText(/unsaved change/i)).not.toBeInTheDocument();
  });

  it('Save PUTs only the changed keys, as a string changes map', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => {
      const calls = (fetch as ReturnType<typeof vi.fn>).mock.calls;
      const put = calls.find((c) => (c[1] as RequestInit).method === 'PUT');
      expect(put).toBeDefined();
      // Only the changed key, its value serialised to a string.
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
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() =>
      expect(screen.queryByText(/unsaved change/i)).not.toBeInTheDocument(),
    );
  });

  it('renders the Paperless test-connection row', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    expect(
      await screen.findByRole('button', { name: /run test/i }),
    ).toBeInTheDocument();
  });

  it('shows a re-index note on a re-index key', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // CHUNK_SIZE and EMBEDDING_MODEL both have requires_reindex: true — each
    // row carries the warning, so there are multiple matches; assert at least
    // one exists.
    const notes = await screen.findAllByText(/requires re-indexing all documents/i);
    expect(notes.length).toBeGreaterThan(0);
  });

  it('shows the coded default value in the control when source is default', async () => {
    // SEARCH_TOP_K is on its coded default — value: null, default_value: 10.
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
    // The stepper should show 10 (the coded default), not 0 (the fallback for
    // a null/missing value).
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
    await screen.findByRole('heading', { level: 2, name: 'Search Server' });
    expect(screen.getByText('default')).toBeInTheDocument();
  });
});
