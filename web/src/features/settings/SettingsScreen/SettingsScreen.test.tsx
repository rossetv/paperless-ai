import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsScreen } from './SettingsScreen';

// A complete settings payload — every key the field model references.
const SETTINGS = {
  PAPERLESS_URL: 'http://paperless.lan:8000',
  PAPERLESS_PUBLIC_URL: 'http://paperless.lan:8000',
  PAPERLESS_TOKEN: '********',
  LLM_PROVIDER: 'openai',
  OCR_PROVIDER: 'openai',
  CLASSIFY_PROVIDER: 'openai',
  SEARCH_PLANNER_PROVIDER: 'openai',
  SEARCH_JUDGE_PROVIDER: 'openai',
  SEARCH_ANSWER_PROVIDER: 'openai',
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

/** Convert the flat map into the wire shape `{ settings: [...] }`. */
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

function renderScreen(path = '/settings', client = newClient()) {
  // useBlocker needs a data router; /library stands in for any other in-app page.
  const router = createMemoryRouter(
    [
      { path: '/settings', element: <SettingsScreen /> },
      { path: '/library', element: <p>Library page</p> },
      { path: '/login', element: <p>Login page</p> },
    ],
    { initialEntries: [path] },
  );
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

describe('SettingsScreen', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows a loading placeholder before the fetch resolves', () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('renders the Settings title and all seven section headings', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Connections' });
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    // No "AI providers" heading: provider choice lives on each step's card.
    for (const name of [
      'Connections',
      'OCR',
      'Classification',
      'Indexing',
      'Search',
      'Automation & Daemons',
      'Logging',
    ]) {
      expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument();
    }
    expect(
      screen.queryByRole('heading', { level: 2, name: 'AI providers' }),
    ).toBeNull();
  });

  it('shows an error placeholder when the fetch fails', async () => {
    mockFetchSequence([{ status: 500, body: { detail: 'boom' } }]);
    renderScreen();
    expect(await screen.findByText(/could not load/i)).toBeInTheDocument();
  });

  it('keeps the loaded settings when a later refetch fails', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 500, body: { detail: 'boom' } },
    ]);
    const client = newClient();
    renderScreen('/settings', client);
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await client.invalidateQueries();
    await waitFor(() =>
      expect(client.getQueryCache().findAll().some((q) => q.state.status === 'error')).toBe(true),
    );
    expect(screen.queryByText(/could not load/i)).not.toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'Top K' })).toBeInTheDocument();
  });

  it('scrolls to the section named in the url once the settings have loaded', async () => {
    const scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    const client = newClient();
    renderScreen('/settings#search', client);
    await screen.findByRole('spinbutton', { name: 'Top K' });
    expect(scrollTo).toHaveBeenCalledTimes(1);
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'instant' }));
    scrollTo.mockRestore();
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
    // The SaveBar stays in the DOM, hidden via inert + CSS transform.
    const message = screen.queryByText(/unsaved change/i);
    if (message !== null) {
      expect(message.closest('[inert]')).not.toBeNull();
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
    const message = screen.queryByText(/unsaved change/i);
    if (message !== null) {
      expect(message.closest('[inert]')).not.toBeNull();
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
    await waitFor(() => {
      const message = screen.queryByText(/unsaved change/i);
      if (message !== null) {
        expect(message.closest('[inert]')).not.toBeNull();
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
    // Match the toast-only phrase, not the per-field "requires re-indexing" notes.
    expect(
      await screen.findByText(/re-embedding your library/i),
    ).toBeInTheDocument();
  });

  // Activates Save the way a keyboard user does: focus it and press Enter.
  async function saveWithKeyboard(): Promise<void> {
    screen.getByRole('button', { name: /save changes/i }).focus();
    await userEvent.keyboard('{Enter}');
  }

  // Holds the save request open; the returned function lets it finish.
  function holdSave(): (body?: object) => void {
    let resolvePut: (value: object) => void = () => {};
    const put = new Promise((resolve) => {
      resolvePut = resolve;
    });
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((_url, init?: RequestInit) =>
      init?.method === 'PUT'
        ? put
        : Promise.resolve(mockResponse({ status: 200, body: toSettingsBody(SETTINGS) })),
    );
    return () =>
      resolvePut(mockResponse({ status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) }));
  }

  it('confirms a plain save with a toast and returns focus to the field last edited', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await saveWithKeyboard();
    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Increase Top K' })).toHaveFocus();
  });

  it('puts focus on the heading, not the field, after a pointer save so no keyboard opens', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByText('Settings saved.');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toHaveFocus();
  });

  it('falls back to the heading when no field was focused, without scrolling the page', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    // fireEvent does not move focus, so no field is remembered and focus rests on the body.
    fireEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByText('Settings saved.');
    const heading = screen.getByRole('heading', { level: 1, name: 'Settings' });
    expect(heading).toHaveFocus();
    const headingCall = focus.mock.contexts.findIndex((el) => el === heading);
    expect(focus.mock.calls[headingCall]).toEqual([{ preventScroll: true }]);
    focus.mockRestore();
  });

  it('keeps focus on Save while a save is pending and sends only one request', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    let resolvePut: (value: object) => void = () => {};
    const put = new Promise((resolve) => {
      resolvePut = resolve;
    });
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((_url, init?: RequestInit) =>
      init?.method === 'PUT'
        ? put
        : Promise.resolve(mockResponse({ status: 200, body: toSettingsBody(SETTINGS) })),
    );
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    // A text query: role queries over the whole settings form are slow enough to time out.
    const saving = (await screen.findByText('Saving…')).closest('button');
    expect(saving).toHaveFocus();
    expect(saving).toBeEnabled();
    await userEvent.click(saving as HTMLButtonElement);
    await userEvent.keyboard('{Enter}');
    const puts = (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === 'PUT',
    );
    expect(puts).toHaveLength(1);
    resolvePut(mockResponse({ status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) }));
    expect(await screen.findByText('Settings saved.')).toBeInTheDocument();
  });

  it('keeps focus on an enabled Save while the save runs and after it fails', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    let rejectPut: (value: object) => void = () => {};
    const put = new Promise((resolve) => {
      rejectPut = resolve;
    });
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(() => put);
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    const saving = (await screen.findByText('Saving…')).closest('button') as HTMLButtonElement;
    expect(saving).toBeEnabled();
    expect(saving).toBe(document.activeElement);
    rejectPut(mockResponse({ status: 422, body: { detail: 'SEARCH_TOP_K is out of range' } }));
    await screen.findByRole('alert');
    const save = screen.getByRole('button', { name: /save changes/i });
    expect(save).toBeEnabled();
    expect(save).toBe(document.activeElement);
  });

  it('returns focus to the field last edited after a save that starts a re-index', async () => {
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
    await saveWithKeyboard();
    await screen.findByText(/re-embedding your library/i);
    expect(screen.getByRole('button', { name: 'Increase Top K' })).toHaveFocus();
  });

  it('leaves focus on an element outside the settings the person moved to while a slow save finishes', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    const finish = holdSave();
    await saveWithKeyboard();
    await screen.findByText('Saving…');
    // An element outside the screen is never remembered as the last field.
    const elsewhere = document.body.appendChild(document.createElement('button'));
    act(() => elsewhere.focus());
    finish();
    await screen.findByText('Settings saved.');
    expect(elsewhere).toHaveFocus();
    elsewhere.remove();
  });

  it('falls back to the heading when the remembered field is disabled before the save finishes', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    const increase = screen.getByRole('button', { name: 'Increase Top K' });
    await userEvent.click(increase);
    const finish = holdSave();
    await saveWithKeyboard();
    await screen.findByText('Saving…');
    increase.setAttribute('disabled', '');
    finish();
    await screen.findByText('Settings saved.');
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toHaveFocus();
  });

  it('clears the saved notice when a later save fails', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      { status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }) },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByText('Settings saved.');
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockResponse({ status: 422, body: { detail: 'SEARCH_TOP_K is out of range' } }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByRole('alert');
    expect(screen.queryByText('Settings saved.')).not.toBeInTheDocument();
  });

  it('clears the re-index notice when a later plain save succeeds', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody(SETTINGS) },
      {
        status: 200,
        body: { ...toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }), reindex_triggered: true },
      },
    ]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByText(/re-embedding your library/i);
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockResponse({ status: 200, body: toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 12 }) }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await screen.findByText('Settings saved.');
    expect(screen.queryByText(/re-embedding your library/i)).not.toBeInTheDocument();
  });

  it('shows the server error in a toast and keeps the edit when the save fails', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const topK = await screen.findByRole('spinbutton', { name: 'Top K' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    // Later calls (the PUT) fail; the first (GET) already resolved.
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      mockResponse({ status: 422, body: { detail: 'SEARCH_TOP_K is out of range' } }),
    );
    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('SEARCH_TOP_K is out of range');
    expect(topK).toHaveValue(11);
  });

  it('warns before unload only while there are unsaved changes', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('spinbutton', { name: 'Top K' });
    const fire = (): boolean =>
      window.dispatchEvent(new Event('beforeunload', { cancelable: true }));
    expect(fire()).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
    expect(fire()).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(fire()).toBe(true);
  });

  describe('leaving with unsaved changes', () => {
    async function editTopK(): Promise<HTMLElement> {
      const topK = await screen.findByRole('spinbutton', { name: 'Top K' });
      await userEvent.click(screen.getByRole('button', { name: 'Increase Top K' }));
      return topK;
    }

    it('asks before an in-app navigation away, with Stay focused', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      await editTopK();
      await act(() => router.navigate('/library'));
      const dialog = await screen.findByRole('dialog', { name: 'Leave without saving?' });
      expect(within(dialog).getByText('Your changes to settings will be lost.')).toBeInTheDocument();
      expect(within(dialog).getByRole('button', { name: 'Stay' })).toHaveFocus();
      expect(router.state.location.pathname).toBe('/settings');
    });

    it('keeps the edits and the place on Stay, and on Escape', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      const topK = await editTopK();
      await act(() => router.navigate('/library'));
      await userEvent.click(await screen.findByRole('button', { name: 'Stay' }));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/settings');
      expect(topK).toHaveValue(11);
      await act(() => router.navigate('/library'));
      await screen.findByRole('dialog');
      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/settings');
      expect(topK).toHaveValue(11);
    });

    it('goes on Leave', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      await editTopK();
      await act(() => router.navigate('/library'));
      await userEvent.click(await screen.findByRole('button', { name: 'Leave' }));
      expect(await screen.findByText('Library page')).toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/library');
    });

    it('does not ask when nothing is unsaved or after Discard', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      await editTopK();
      await userEvent.click(screen.getByRole('button', { name: /discard/i }));
      await act(() => router.navigate('/library'));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/library');
    });

    it('does not ask after a save', async () => {
      mockFetchSequence([
        { status: 200, body: toSettingsBody(SETTINGS) },
        { status: 200, body: { ...toSettingsBody({ ...SETTINGS, SEARCH_TOP_K: 11 }), reindex_triggered: false } },
      ]);
      const router = renderScreen();
      await editTopK();
      await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
      await screen.findByText('Settings saved.');
      await act(() => router.navigate('/library'));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/library');
    });

    it('lets a sign-out through to /login without asking', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      await editTopK();
      await act(() => router.navigate('/login'));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.pathname).toBe('/login');
    });

    it('never asks for a section change within Settings', async () => {
      mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
      const router = renderScreen();
      await editTopK();
      await act(() => router.navigate('/settings#logging'));
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
      expect(router.state.location.hash).toBe('#logging');
    });
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
    // All three services are shown regardless of LLM_PROVIDER.
    expect(screen.getByRole('button', { name: 'Test Paperless-ngx' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test OpenAI' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test Ollama' })).toBeInTheDocument();
  });

  it('co-locates a Provider radiogroup on each pipeline step (no separate AI providers section)', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'OCR' });

    // OCR, Classification and Indexing each carry a "Provider" radiogroup.
    const ocrRegion = screen.getByRole('region', { name: 'OCR' });
    expect(
      within(ocrRegion).getByRole('radiogroup', { name: 'Provider' }),
    ).toBeInTheDocument();
    const indexingRegion = screen.getByRole('region', { name: 'Indexing' });
    expect(
      within(indexingRegion).getByRole('radiogroup', { name: 'Provider' }),
    ).toBeInTheDocument();

    // Search has an independent provider radiogroup per sub-step.
    const searchRegion = screen.getByRole('region', { name: 'Search' });
    for (const name of ['Planner provider', 'Judge provider', 'Answer provider']) {
      expect(
        within(searchRegion).getByRole('radiogroup', { name }),
      ).toBeInTheDocument();
    }
  });

  it('cross-section conditional: EMBEDDING_PROVIDER=openai renders a combobox for Embedding model', async () => {
    // SETTINGS seeds EMBEDDING_PROVIDER='openai', so the Indexing control resolves to a select.
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Indexing' });
    expect(screen.getByRole('combobox', { name: 'Embedding model' })).toBeInTheDocument();
  });

  it('cross-section conditional: EMBEDDING_PROVIDER=ollama renders a textbox for Embedding model', async () => {
    // With 'ollama' the Indexing control falls back to free text.
    const ollamaSettings = { ...SETTINGS, EMBEDDING_PROVIDER: 'ollama' };
    mockFetchSequence([{ status: 200, body: toSettingsBody(ollamaSettings) }]);
    renderScreen();
    await screen.findByRole('heading', { level: 2, name: 'Indexing' });
    expect(screen.getByRole('textbox', { name: 'Embedding model' })).toBeInTheDocument();
  });

  it('reindex pill is present inside the Indexing region for the Embeddings card', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    // EMBEDDING_PROVIDER is a reindex key in the Indexing region, so the amber pill appears there.
    const indexingRegion = await screen.findByRole('region', { name: 'Indexing' });
    const pills = Array.from(indexingRegion.querySelectorAll('*')).filter(
      (el) => el.textContent?.match(/rebuilds the index on save/i),
    );
    expect(pills.length).toBeGreaterThan(0);
  });

  it("shows the OCR reasoning-effort row when OCR is on OpenAI", async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody({ ...SETTINGS, OCR_PROVIDER: 'openai' }) },
    ]);
    renderScreen();
    const ocrRegion = await screen.findByRole('region', { name: 'OCR' });
    expect(
      within(ocrRegion).getByRole('radiogroup', { name: 'Reasoning effort' }),
    ).toBeInTheDocument();
  });

  it("hides the OCR reasoning-effort row when OCR is on Ollama (OpenAI-only param)", async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody({ ...SETTINGS, OCR_PROVIDER: 'ollama' }) },
    ]);
    renderScreen();
    const ocrRegion = await screen.findByRole('region', { name: 'OCR' });
    expect(
      within(ocrRegion).queryByRole('radiogroup', { name: 'Reasoning effort' }),
    ).toBeNull();
  });

  it('locks the Ollama provider option until OLLAMA_BASE_URL is configured', async () => {
    mockFetchSequence([
      { status: 200, body: toSettingsBody({ ...SETTINGS, OLLAMA_BASE_URL: '' }) },
    ]);
    renderScreen();
    const ocrRegion = await screen.findByRole('region', { name: 'OCR' });
    const providerGroup = within(ocrRegion).getByRole('radiogroup', { name: 'Provider' });
    const ollama = within(providerGroup).getByRole('radio', { name: 'Ollama' });
    expect(ollama).toBeDisabled();
    // OpenAI stays selectable — only the unconfigured provider is locked.
    expect(within(providerGroup).getByRole('radio', { name: 'OpenAI' })).toBeEnabled();
  });

  it('unlocks the Ollama provider option once OLLAMA_BASE_URL is set', async () => {
    mockFetchSequence([{ status: 200, body: toSettingsBody(SETTINGS) }]);
    renderScreen();
    const ocrRegion = await screen.findByRole('region', { name: 'OCR' });
    const providerGroup = within(ocrRegion).getByRole('radiogroup', { name: 'Provider' });
    expect(within(providerGroup).getByRole('radio', { name: 'Ollama' })).toBeEnabled();
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
    await screen.findByRole('spinbutton', { name: 'Chunk size' });
    await userEvent.click(screen.getByRole('button', { name: 'Increase Chunk size' }));
    // Scope to the SaveBar (the aria-live region) to avoid matching static reindex pills/hints.
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
