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
} from './hooks';
import type { SearchResponse, FacetsResponse, StatsResponse } from './types';
import { Unauthenticated } from './client';

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
