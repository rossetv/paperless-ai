/**
 * Tests for the TanStack Query hooks (hooks.ts).
 *
 * Each hook is tested via a minimal QueryClient wrapper. `fetch` is mocked
 * globally; no real network calls are made.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import {
  useSearch,
  useFacets,
  useStats,
  useLogin,
  useLogout,
  useMe,
  useSetup,
  useSetupStatus,
  usePublicStats,
  useRecentSearches,
  useUsers,
  useCreateUser,
  useUpdateUser,
  useDeleteUser,
  useApiKeys,
  useCreateApiKey,
  useUpdateApiKey,
  useDeleteApiKey,
  useSettings,
  useUpdateSettings,
  useTestConnection,
  useDocuments,
  useIndexStatus,
  useIndexActivity,
  useFailedDocuments,
  useRebuildIndex,
  useReconcile,
} from './hooks';
import type { SearchResponse, FacetsResponse, StatsResponse } from './types';
import { Unauthenticated, ApiError } from './client';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeWrapper(): React.FC<{ children: React.ReactNode }> {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return ({ children }) =>
    React.createElement(QueryClientProvider, { client }, children);
}

function mockFetch(status: number, body: unknown): void {
  const serialised = body !== null ? JSON.stringify(body) : '';
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      headers: new Headers(serialised ? { 'content-type': 'application/json' } : {}),
      text: () => Promise.resolve(serialised),
      json: () => Promise.resolve(body),
    }),
  );
}

const SEARCH_RESPONSE: SearchResponse = {
  answer: 'The boiler warranty expires next year.',
  sources: [],
  plan: { semantic_queries: ['boiler'], keyword_terms: ['warranty'], sub_questions: [] },
  stats: { llm_calls: 1, latency_ms: 200, refined: false },
};

const FACETS_RESPONSE: FacetsResponse = {
  correspondents: [{ kind: 'correspondent', id: 1, name: 'HMRC' }],
  document_types: [],
  tags: [],
  earliest: '2010-01-01',
  latest: '2024-12-31',
};

const STATS_RESPONSE: StatsResponse = {
  document_count: 500,
  chunk_count: 2000,
  last_reconcile_at: '2026-05-20T09:00:00Z',
  embedding_model: 'text-embedding-3-small',
};

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// useSearch
// ---------------------------------------------------------------------------

describe('useSearch', () => {
  it('returns loading state initially then data on success', async () => {
    mockFetch(200, SEARCH_RESPONSE);
    const { result } = renderHook(
      () => useSearch({ query: 'boiler warranty' }),
      { wrapper: makeWrapper() },
    );
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.answer).toBe('The boiler warranty expires next year.');
  });

  it('exposes error state when the request fails', async () => {
    mockFetch(500, { detail: 'Internal Server Error' });
    const { result } = renderHook(
      () => useSearch({ query: 'boiler warranty' }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeDefined();
  });

  it('surfaces Unauthenticated error on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    const { result } = renderHook(
      () => useSearch({ query: 'test' }),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });

  it('does not fetch when query is empty', async () => {
    mockFetch(200, SEARCH_RESPONSE);
    const { result } = renderHook(
      () => useSearch({ query: '' }),
      { wrapper: makeWrapper() },
    );
    // With an empty query the hook should be disabled (pending state, not fetching)
    expect(result.current.isPending).toBe(true);
    expect(result.current.isFetching).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// useFacets
// ---------------------------------------------------------------------------

describe('useFacets', () => {
  it('returns loading state initially then data on success', async () => {
    mockFetch(200, FACETS_RESPONSE);
    const { result } = renderHook(() => useFacets(), { wrapper: makeWrapper() });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.correspondents[0]?.name).toBe('HMRC');
    expect(result.current.data?.earliest).toBe('2010-01-01');
  });

  it('exposes error state on failure', async () => {
    mockFetch(500, { detail: 'error' });
    const { result } = renderHook(() => useFacets(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it('surfaces Unauthenticated error on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    const { result } = renderHook(() => useFacets(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });
});

// ---------------------------------------------------------------------------
// useStats
// ---------------------------------------------------------------------------

describe('useStats', () => {
  it('returns loading state initially then data on success', async () => {
    mockFetch(200, STATS_RESPONSE);
    const { result } = renderHook(() => useStats(), { wrapper: makeWrapper() });
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.document_count).toBe(500);
    expect(result.current.data?.embedding_model).toBe('text-embedding-3-small');
  });

  it('exposes error state on failure', async () => {
    mockFetch(503, { status: 'index-not-ready' });
    const { result } = renderHook(() => useStats(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it('surfaces Unauthenticated error on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    const { result } = renderHook(() => useStats(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });
});

// ---------------------------------------------------------------------------
// useLogin
// ---------------------------------------------------------------------------

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

describe('useLogin', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useLogin(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the user on correct credentials', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const { result } = renderHook(() => useLogin(), { wrapper: makeWrapper() });
    result.current.mutate({ username: 'alex.morgan', password: 'secret123', remember: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user.username).toBe('alex.morgan');
  });

  it('surfaces Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Invalid credentials' });
    const { result } = renderHook(() => useLogin(), { wrapper: makeWrapper() });
    result.current.mutate({ username: 'x', password: 'y', remember: false });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });
});

// ---------------------------------------------------------------------------
// useLogout
// ---------------------------------------------------------------------------

describe('useLogout', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useLogout(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves on a 204 response', async () => {
    mockFetch(204, null);
    const { result } = renderHook(() => useLogout(), { wrapper: makeWrapper() });
    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useMe
// ---------------------------------------------------------------------------

describe('useMe', () => {
  it('returns the current user on success', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const { result } = renderHook(() => useMe(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user.role).toBe('admin');
  });

  it('surfaces Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthenticated' });
    const { result } = renderHook(() => useMe(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });
});

// ---------------------------------------------------------------------------
// useSetupStatus
// ---------------------------------------------------------------------------

describe('useSetupStatus', () => {
  it('returns { needed } on success', async () => {
    mockFetch(200, { needed: true });
    const { result } = renderHook(() => useSetupStatus(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.needed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// usePublicStats
// ---------------------------------------------------------------------------

describe('usePublicStats', () => {
  it('returns the public counts on success', async () => {
    mockFetch(200, { document_count: 14238, chunk_count: 187000 });
    const { result } = renderHook(() => usePublicStats(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.document_count).toBe(14238);
  });

  it('exposes an error state on failure (caller must degrade)', async () => {
    mockFetch(500, { detail: 'error' });
    const { result } = renderHook(() => usePublicStats(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useSetup
// ---------------------------------------------------------------------------

describe('useSetup', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useSetup(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the created admin user on success', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const { result } = renderHook(() => useSetup(), { wrapper: makeWrapper() });
    result.current.mutate({ token: 't', username: 'admin', password: 'longenough' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user.role).toBe('admin');
  });

  it('surfaces an ApiError on a 403 bad-token response', async () => {
    mockFetch(403, { detail: 'Invalid setup token' });
    const { result } = renderHook(() => useSetup(), { wrapper: makeWrapper() });
    result.current.mutate({ token: 'bad', username: 'admin', password: 'longenough' });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useRecentSearches
// ---------------------------------------------------------------------------

describe('useRecentSearches', () => {
  it('returns the recent searches on success', async () => {
    mockFetch(200, {
      searches: [
        { query: 'npower 2024', created_at: '2026-05-22T10:00:00Z' },
        { query: 'bupa dental', created_at: '2026-05-21T09:00:00Z' },
      ],
    });
    const { result } = renderHook(() => useRecentSearches(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.searches).toHaveLength(2);
    expect(result.current.data?.searches[0]?.query).toBe('npower 2024');
  });

  it('surfaces Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthenticated' });
    const { result } = renderHook(() => useRecentSearches(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Unauthenticated);
  });
});

// ---------------------------------------------------------------------------
// Wave 3 — user-management hooks
// ---------------------------------------------------------------------------

describe('useUsers', () => {
  it('returns the user list on success', async () => {
    mockFetch(200, { users: [SAMPLE_USER] });
    const { result } = renderHook(() => useUsers(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.users[0]?.username).toBe('alex.morgan');
  });
});

describe('useCreateUser', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useCreateUser(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the created user', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const { result } = renderHook(() => useCreateUser(), { wrapper: makeWrapper() });
    result.current.mutate({
      username: 'sam.patel',
      password: 'password1',
      display_name: 'Sam Patel',
      email: 'sam@home.lan',
      role: 'member',
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user.id).toBe(1);
  });
});

describe('useUpdateUser', () => {
  it('resolves with the updated user', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const { result } = renderHook(() => useUpdateUser(), { wrapper: makeWrapper() });
    result.current.mutate({ id: 7, body: { role: 'admin' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.user.role).toBe('admin');
  });
});

describe('useDeleteUser', () => {
  it('resolves on a 204 response', async () => {
    mockFetch(204, null);
    const { result } = renderHook(() => useDeleteUser(), { wrapper: makeWrapper() });
    result.current.mutate(7);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('surfaces ApiError on a 409 (last-admin guard)', async () => {
    mockFetch(409, { detail: 'Cannot delete the last admin' });
    const { result } = renderHook(() => useDeleteUser(), { wrapper: makeWrapper() });
    result.current.mutate(1);
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
  });
});

// ---------------------------------------------------------------------------
// Wave 3 — API-key hooks
// ---------------------------------------------------------------------------

const SAMPLE_KEY = {
  id: 1,
  name: 'Claude · MCP integration',
  key_prefix: 'sk-pls-aF82C',
  scopes: ['mcp'] as const,
  owner_id: 1,
  owner_name: 'Alex Morgan',
  created_at: '2026-01-12T00:00:00Z',
  expires_at: null,
  last_used_at: '2026-05-22T09:00:00Z',
  revoked_at: null,
  request_count: 184602,
};

describe('useApiKeys', () => {
  it('returns the key list on success', async () => {
    mockFetch(200, { keys: [SAMPLE_KEY] });
    const { result } = renderHook(() => useApiKeys(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.keys[0]?.key_prefix).toBe('sk-pls-aF82C');
  });
});

describe('useCreateApiKey', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useCreateApiKey(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the one-time secret', async () => {
    mockFetch(200, { api_key: SAMPLE_KEY, secret: 'sk-pls-aF82CdeadbeefSECRET' });
    const { result } = renderHook(() => useCreateApiKey(), { wrapper: makeWrapper() });
    result.current.mutate({ name: 'n8n', scopes: ['api'], expires_at: null });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.secret).toBe('sk-pls-aF82CdeadbeefSECRET');
  });
});

describe('useUpdateApiKey', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useUpdateApiKey(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the updated key on a successful edit', async () => {
    mockFetch(200, { api_key: { ...SAMPLE_KEY, name: 'renamed' } });
    const { result } = renderHook(() => useUpdateApiKey(), { wrapper: makeWrapper() });
    result.current.mutate({ id: 1, body: { name: 'renamed' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.api_key.name).toBe('renamed');
  });
});

describe('useDeleteApiKey', () => {
  it('resolves on a 204 response', async () => {
    mockFetch(204, null);
    const { result } = renderHook(() => useDeleteApiKey(), { wrapper: makeWrapper() });
    result.current.mutate(3);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// Wave 4 — settings hooks
// ---------------------------------------------------------------------------

const SETTINGS_RESPONSE = {
  settings: [
    {
      key: 'SEARCH_TOP_K',
      value: '10',
      source: 'default',
      is_secret: false,
      requires_reindex: false,
    },
    {
      key: 'PAPERLESS_URL',
      value: 'http://x',
      source: 'database',
      is_secret: false,
      requires_reindex: false,
    },
  ],
};

describe('useSettings', () => {
  it('returns the settings item list on success', async () => {
    mockFetch(200, SETTINGS_RESPONSE);
    const { result } = renderHook(() => useSettings(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const topK = result.current.data?.settings.find((s) => s.key === 'SEARCH_TOP_K');
    expect(topK?.value).toBe('10');
  });
});

describe('useUpdateSettings', () => {
  it('mutation starts idle', () => {
    const { result } = renderHook(() => useUpdateSettings(), { wrapper: makeWrapper() });
    expect(result.current.isIdle).toBe(true);
  });

  it('resolves with the re-read settings on success', async () => {
    mockFetch(200, SETTINGS_RESPONSE);
    const { result } = renderHook(() => useUpdateSettings(), { wrapper: makeWrapper() });
    result.current.mutate({ changes: { SEARCH_TOP_K: '20' } });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const topK = result.current.data?.settings.find((s) => s.key === 'SEARCH_TOP_K');
    expect(topK?.value).toBe('10');
  });

  it('surfaces ApiError on a 400 validation failure', async () => {
    mockFetch(400, { detail: 'invalid' });
    const { result } = renderHook(() => useUpdateSettings(), { wrapper: makeWrapper() });
    result.current.mutate({ changes: { CHUNK_OVERLAP: '99999' } });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ApiError);
  });
});

describe('useTestConnection', () => {
  it('resolves with the probe result', async () => {
    mockFetch(200, { ok: true, document_count: 14238, detail: 'Connected.' });
    const { result } = renderHook(() => useTestConnection(), { wrapper: makeWrapper() });
    result.current.mutate({ paperless_url: 'http://x', paperless_token: 'tok' });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.document_count).toBe(14238);
  });
});

describe('useDocuments', () => {
  it('calls getDocuments with the supplied query and returns data', async () => {
    const response = {
      documents: [],
      total: 0,
      page: 1,
      page_size: 24,
    };
    mockFetch(200, response);

    const { result } = renderHook(
      () =>
        useDocuments({
          page: 1,
          page_size: 24,
          sort: 'created',
          descending: true,
          tag_ids: [],
        }),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(response);
  });
});

// ---------------------------------------------------------------------------
// Wave 6 — index-operations hooks
// ---------------------------------------------------------------------------

describe('index-operations hooks', () => {
  /**
   * STATUS_BODY mirrors `IndexStatusResponse` from `wire.py` exactly:
   *   health: "ok" | "degraded" | "down"  (NOT an object)
   *   daemons[].fields: name, state, detail, processed_count, last_heartbeat
   */
  const STATUS_BODY = {
    health: 'ok',
    daemons: [
      {
        name: 'ocr',
        state: 'running',
        detail: '3 in flight',
        processed_count: 412,
        last_heartbeat: '2026-05-22T08:59:50Z',
      },
    ],
  };

  it('useIndexStatus resolves with the status payload — health is a string', async () => {
    mockFetch(200, STATUS_BODY);
    const { result } = renderHook(() => useIndexStatus(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // health is the wire.py string verdict, not an object
    expect(result.current.data?.health).toBe('ok');
    expect(result.current.data?.daemons[0]?.name).toBe('ocr');
    expect(result.current.data?.daemons[0]?.processed_count).toBe(412);
  });

  it('useIndexActivity resolves with cycles (not entries)', async () => {
    /**
     * Body mirrors `IndexActivityResponse` from `wire.py`:
     *   cycles: list[ReconcileCycleResponse]
     *   (id, kind, started_at, finished_at, ok, summary, detail)
     */
    mockFetch(200, {
      cycles: [
        {
          id: 1,
          kind: 'sync',
          started_at: '2026-05-22T09:00:00Z',
          finished_at: '2026-05-22T09:00:02Z',
          ok: true,
          summary: { indexed: 12, failed: 0 },
          detail: 'incremental sync complete',
        },
      ],
    });
    const { result } = renderHook(() => useIndexActivity(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.cycles).toHaveLength(1);
    expect(result.current.data?.cycles[0]?.id).toBe(1);
    expect(result.current.data?.cycles[0]?.ok).toBe(true);
  });

  it('useFailedDocuments resolves with the failed-document list — title nullable', async () => {
    /**
     * Body mirrors `IndexFailedResponse` from `wire.py`:
     *   documents: list[FailedDocumentResponse]
     *   (document_id, title: str|None, failure_count)
     */
    mockFetch(200, {
      documents: [
        {
          document_id: 8421,
          title: null, // backend sends null when no indexed row exists
          failure_count: 3,
        },
      ],
    });
    const { result } = renderHook(() => useFailedDocuments(), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.documents[0]?.document_id).toBe(8421);
    expect(result.current.data?.documents[0]?.failure_count).toBe(3);
    expect(result.current.data?.documents[0]?.title).toBeNull();
  });

  it('useRebuildIndex resolves with the RebuildResponse body', async () => {
    /**
     * Body mirrors `RebuildResponse` from `wire.py`:
     *   accepted: bool
     *   detail: str
     */
    mockFetch(200, {
      accepted: true,
      detail: 'Index rebuild triggered.',
    });
    const { result } = renderHook(() => useRebuildIndex(), {
      wrapper: makeWrapper(),
    });
    const response = await result.current.mutateAsync();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // result is NOT void — carries accepted + detail
    expect(response.accepted).toBe(true);
    expect(typeof response.detail).toBe('string');
  });

  it('useReconcile resolves on a successful POST', async () => {
    mockFetch(202, null);
    const { result } = renderHook(() => useReconcile(), {
      wrapper: makeWrapper(),
    });
    await result.current.mutateAsync();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });
});
