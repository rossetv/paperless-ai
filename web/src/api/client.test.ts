/**
 * Tests for the typed fetch wrapper (client.ts).
 *
 * All tests mock global `fetch`; no real network calls are made.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  Unauthenticated,
  ApiError,
  login,
  logout,
  me,
  setup,
  setupStatus,
  publicStats,
  search,
  getFacets,
  getStats,
  getHealthz,
  postReconcile,
  getRecentSearches,
  documentPdfUrl,
} from './client';
import type { SearchRequest, FacetsResponse, StatsResponse, SearchResponse } from './types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

function capturedFetch(): ReturnType<typeof vi.fn> {
  return vi.mocked(globalThis.fetch);
}

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
// Shared fixtures
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

// ---------------------------------------------------------------------------
// credentials: 'include' — every request carries the session cookie
// ---------------------------------------------------------------------------

describe('every request sends credentials: include', () => {
  it('login sends credentials include', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    await login({ username: 'u', password: 'p', remember: false });
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });

  it('search sends credentials include', async () => {
    const body: SearchResponse = {
      answer: 'answer',
      sources: [],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 1, latency_ms: 100, refined: false },
    };
    mockFetch(200, body);
    const req: SearchRequest = { query: 'test' };
    await search(req);
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });

  it('getFacets sends credentials include', async () => {
    const body: FacetsResponse = {
      correspondents: [],
      document_types: [],
      tags: [],
      earliest: null,
      latest: null,
    };
    mockFetch(200, body);
    await getFacets();
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });

  it('getStats sends credentials include', async () => {
    const body: StatsResponse = {
      document_count: 0,
      chunk_count: 0,
      last_reconcile_at: null,
      embedding_model: null,
    };
    mockFetch(200, body);
    await getStats();
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });

  it('getHealthz sends credentials include', async () => {
    mockFetch(200, { status: 'ok' });
    await getHealthz();
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });

  it('postReconcile sends credentials include', async () => {
    mockFetch(202, null);
    await postReconcile();
    const [, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
  });
});

// ---------------------------------------------------------------------------
// 401 → Unauthenticated (distinct error class)
// ---------------------------------------------------------------------------

describe('401 response surfaces as Unauthenticated', () => {
  it('search throws Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    await expect(search({ query: 'test' })).rejects.toBeInstanceOf(Unauthenticated);
  });

  it('getFacets throws Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    await expect(getFacets()).rejects.toBeInstanceOf(Unauthenticated);
  });

  it('getStats throws Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    await expect(getStats()).rejects.toBeInstanceOf(Unauthenticated);
  });

  it('Unauthenticated is not an ApiError', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    await expect(search({ query: 'test' })).rejects.not.toBeInstanceOf(ApiError);
  });

  it('Unauthenticated carries the 401 status', async () => {
    mockFetch(401, { detail: 'Unauthorised' });
    let caught: unknown;
    try {
      await search({ query: 'test' });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(Unauthenticated);
    expect((caught as Unauthenticated).status).toBe(401);
  });
});

// ---------------------------------------------------------------------------
// Non-401 non-2xx → ApiError
// ---------------------------------------------------------------------------

describe('non-2xx non-401 responses throw ApiError', () => {
  it('500 response throws ApiError', async () => {
    mockFetch(500, { detail: 'Internal Server Error' });
    await expect(search({ query: 'test' })).rejects.toBeInstanceOf(ApiError);
  });

  it('ApiError carries the HTTP status', async () => {
    mockFetch(503, { status: 'index-not-ready' });
    let caught: unknown;
    try {
      await getHealthz();
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(503);
  });
});

// ---------------------------------------------------------------------------
// Successful responses parse into the correct typed shapes
// ---------------------------------------------------------------------------

describe('successful responses parse into typed shapes', () => {
  it('login resolves with the user object', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const result = await login({ username: 'alex.morgan', password: 'secret123', remember: false });
    expect(result.user.username).toBe('alex.morgan');
  });

  it('search resolves with SearchResponse shape', async () => {
    const body: SearchResponse = {
      answer: 'The boiler warranty expires 2025.',
      sources: [
        {
          document_id: 42,
          title: 'Boiler Warranty',
          correspondent: 'Acme Ltd',
          document_type: 'Warranty',
          created: '2020-01-15',
          snippet: '…warranty expires…',
          paperless_url: 'http://paperless/documents/42/',
          score: 0.91,
        },
      ],
      plan: {
        semantic_queries: ['boiler warranty expiry date'],
        keyword_terms: ['boiler', 'warranty'],
        sub_questions: [],
      },
      stats: { llm_calls: 2, latency_ms: 450, refined: false },
    };
    mockFetch(200, body);
    const result = await search({ query: 'When does the boiler warranty expire?' });
    expect(result.answer).toBe('The boiler warranty expires 2025.');
    expect(result.sources).toHaveLength(1);
    expect(result.sources[0]?.document_id).toBe(42);
    expect(result.plan.semantic_queries).toEqual(['boiler warranty expiry date']);
    expect(result.stats.llm_calls).toBe(2);
  });

  it('getFacets resolves with FacetsResponse shape', async () => {
    const body: FacetsResponse = {
      correspondents: [{ kind: 'correspondent', id: 1, name: 'HMRC' }],
      document_types: [{ kind: 'document_type', id: 2, name: 'Tax Return' }],
      tags: [],
      earliest: '2010-01-01',
      latest: '2024-12-31',
    };
    mockFetch(200, body);
    const result = await getFacets();
    expect(result.correspondents[0]?.name).toBe('HMRC');
    expect(result.document_types[0]?.id).toBe(2);
    expect(result.earliest).toBe('2010-01-01');
    expect(result.latest).toBe('2024-12-31');
  });

  it('getStats resolves with StatsResponse shape', async () => {
    const body: StatsResponse = {
      document_count: 1234,
      chunk_count: 5678,
      last_reconcile_at: '2026-05-20T10:00:00Z',
      embedding_model: 'text-embedding-3-small',
    };
    mockFetch(200, body);
    const result = await getStats();
    expect(result.document_count).toBe(1234);
    expect(result.embedding_model).toBe('text-embedding-3-small');
  });

  it('getHealthz resolves with status string', async () => {
    mockFetch(200, { status: 'ok' });
    const result = await getHealthz();
    expect(result.status).toBe('ok');
  });

  it('postReconcile resolves without throwing on 202', async () => {
    mockFetch(202, null);
    await expect(postReconcile()).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// Empty-body guard — a 200 with empty content must not throw a SyntaxError
// ---------------------------------------------------------------------------

describe('empty-body guard', () => {
  it('resolves to undefined when the response body is empty (content-length 0)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-length': '0' }),
        text: () => Promise.resolve(''),
        json: () => { throw new SyntaxError('Unexpected end of JSON input'); },
      }),
    );
    await expect(getHealthz()).resolves.toBeUndefined();
  });

  it('resolves to undefined when the response body is empty (empty text, no content-length)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        text: () => Promise.resolve(''),
        json: () => { throw new SyntaxError('Unexpected end of JSON input'); },
      }),
    );
    await expect(getHealthz()).resolves.toBeUndefined();
  });

  it('still parses JSON when the body is present', async () => {
    mockFetch(200, { status: 'ok' });
    const result = await getHealthz();
    expect(result.status).toBe('ok');
  });
});

// ---------------------------------------------------------------------------
// Correct HTTP methods and URLs
// ---------------------------------------------------------------------------

describe('correct HTTP methods and endpoint paths', () => {
  it('login POSTs to /api/auth/login', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    await login({ username: 'u', password: 'p', remember: false });
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/login$/);
    expect(init.method).toBe('POST');
  });

  it('search POSTs to /api/search', async () => {
    mockFetch(200, {
      answer: '',
      sources: [],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 0, latency_ms: 0, refined: false },
    });
    await search({ query: 'q' });
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/search$/);
    expect(init.method).toBe('POST');
  });

  it('getFacets GETs /api/facets', async () => {
    mockFetch(200, {
      correspondents: [],
      document_types: [],
      tags: [],
      earliest: null,
      latest: null,
    });
    await getFacets();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/facets$/);
    expect(init.method).toBe('GET');
  });

  it('getStats GETs /api/stats', async () => {
    mockFetch(200, {
      document_count: 0,
      chunk_count: 0,
      last_reconcile_at: null,
      embedding_model: null,
    });
    await getStats();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/stats$/);
    expect(init.method).toBe('GET');
  });

  it('getHealthz GETs /api/healthz', async () => {
    mockFetch(200, { status: 'ok' });
    await getHealthz();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/healthz$/);
    expect(init.method).toBe('GET');
  });

  it('postReconcile POSTs to /api/reconcile', async () => {
    mockFetch(202, null);
    await postReconcile();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/reconcile$/);
    expect(init.method).toBe('POST');
  });
});

// ---------------------------------------------------------------------------
// Wave 1 — accounts endpoints
// ---------------------------------------------------------------------------

describe('Wave 1 accounts endpoints', () => {
  it('setupStatus GETs /api/setup/status and returns { needed }', async () => {
    mockFetch(200, { needed: true });
    const result = await setupStatus();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/setup\/status$/);
    expect(init.method).toBe('GET');
    expect(result.needed).toBe(true);
  });

  it('setup POSTs /api/setup with token, username, password', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const result = await setup({ token: 't', username: 'admin', password: 'password1' });
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/setup$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      token: 't',
      username: 'admin',
      password: 'password1',
    });
    expect(result.user.username).toBe('alex.morgan');
  });

  it('login POSTs /api/auth/login with username, password, remember', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const result = await login({ username: 'alex.morgan', password: 'secret123', remember: true });
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/login$/);
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body as string)).toEqual({
      username: 'alex.morgan',
      password: 'secret123',
      remember: true,
    });
    expect(result.user.role).toBe('admin');
  });

  it('logout POSTs /api/auth/logout and resolves on 204', async () => {
    mockFetch(204, null);
    await expect(logout()).resolves.toBeUndefined();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/logout$/);
    expect(init.method).toBe('POST');
  });

  it('me GETs /api/auth/me and returns the current user', async () => {
    mockFetch(200, { user: SAMPLE_USER });
    const result = await me();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/auth\/me$/);
    expect(init.method).toBe('GET');
    expect(result.user.id).toBe(1);
  });

  it('me throws Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthenticated' });
    await expect(me()).rejects.toBeInstanceOf(Unauthenticated);
  });

  it('publicStats GETs /api/stats/public', async () => {
    mockFetch(200, { document_count: 14238, chunk_count: 187000 });
    const result = await publicStats();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/stats\/public$/);
    expect(init.method).toBe('GET');
    expect(result.document_count).toBe(14238);
  });
});

// ---------------------------------------------------------------------------
// Wave 2 — search-redesign endpoints
// ---------------------------------------------------------------------------

describe('Wave 2 search endpoints', () => {
  it('getRecentSearches GETs /api/recent-searches', async () => {
    mockFetch(200, {
      searches: [{ query: 'npower 2024', searched_at: '2026-05-22T10:00:00Z' }],
    });
    const result = await getRecentSearches();
    const [url, init] = capturedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/recent-searches$/);
    expect(init.method).toBe('GET');
    expect(result.searches[0]?.query).toBe('npower 2024');
  });

  it('getRecentSearches throws Unauthenticated on 401', async () => {
    mockFetch(401, { detail: 'Unauthenticated' });
    await expect(getRecentSearches()).rejects.toBeInstanceOf(Unauthenticated);
  });

  it('documentPdfUrl builds the proxied PDF path for a document id', () => {
    expect(documentPdfUrl(9823)).toMatch(/\/api\/documents\/9823\/pdf$/);
  });
});
