import { describe, it, expect, vi, afterEach } from 'vitest';
import { ApiError, Unauthenticated } from './core';
import { streamSearch, parseNdjson, StreamError } from './searchStream';
import type { StreamEvent } from '../types';

/** Build a `ReadableStream<Uint8Array>` from a list of string chunks. */
function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(encoder.encode(chunks[i] ?? ''));
        i += 1;
      } else {
        controller.close();
      }
    },
  });
}

/** Drain an async generator of events into an array. */
async function collect(
  gen: AsyncGenerator<StreamEvent>,
): Promise<StreamEvent[]> {
  const out: StreamEvent[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

describe('parseNdjson', () => {
  it('reassembles a line split across two chunks', async () => {
    // The first chunk cuts the JSON mid-key ("ph|ase"); the reader must buffer
    // the partial trailing line and only parse once the newline arrives.
    const chunks = [
      '{"type":"phase_start","seq":1,"ph',
      'ase":"plan","label":"Planning"}\n',
      '{"type":"result","seq":2,"result":{}}\n',
    ];
    const events = await collect(parseNdjson(streamFrom(chunks)));
    expect(events.map((e) => e.type)).toEqual(['phase_start', 'result']);
    expect((events[0] as { phase: string }).phase).toBe('plan');
    expect(events[1]?.seq).toBe(2);
  });

  it('flushes a final line that has no trailing newline', async () => {
    // The terminal frame may arrive without a closing "\n"; the buffered
    // remainder must still be parsed when the stream ends.
    const chunks = ['{"type":"error","seq":9,"kind":"internal","message":"boom"}'];
    const events = await collect(parseNdjson(streamFrom(chunks)));
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: 'error',
      seq: 9,
      kind: 'internal',
      message: 'boom',
    });
  });

  it('handles several whole lines arriving in one chunk', async () => {
    const chunks = [
      '{"type":"phase_start","seq":1,"phase":"plan","label":"Planning"}\n' +
        '{"type":"phase_done","seq":2,"phase":"plan","label":"Planning","detail":{},"tokens":null,"cost":null,"ms":3}\n',
    ];
    const events = await collect(parseNdjson(streamFrom(chunks)));
    expect(events.map((e) => e.type)).toEqual(['phase_start', 'phase_done']);
  });

  it('ignores blank lines between frames', async () => {
    const chunks = [
      '{"type":"phase_start","seq":1,"phase":"plan","label":"Planning"}\n',
      '\n',
      '{"type":"result","seq":2,"result":{}}\n',
    ];
    const events = await collect(parseNdjson(streamFrom(chunks)));
    expect(events.map((e) => e.type)).toEqual(['phase_start', 'result']);
  });

  it('throws when a stream has no body', async () => {
    await expect(collect(parseNdjson(null))).rejects.toBeInstanceOf(StreamError);
  });
});

describe('streamSearch', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Stub `fetch` to return a Response-like object with the given status/body. */
  function mockFetch(status: number, body?: ReadableStream<Uint8Array> | null) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      body: body ?? null,
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('POSTs to /api/search/stream with the body and credentials', async () => {
    const fetchMock = mockFetch(200, streamFrom([]));
    await streamSearch({ query: 'invoice', filters: null });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/search/stream');
    expect(init.method).toBe('POST');
    expect(init.credentials).toBe('include');
    expect(init.headers).toMatchObject({ 'Content-Type': 'application/json' });
    expect(JSON.parse(init.body as string)).toEqual({
      query: 'invoice',
      filters: null,
    });
  });

  it('forwards an AbortSignal to fetch', async () => {
    const fetchMock = mockFetch(200, streamFrom([]));
    const controller = new AbortController();
    await streamSearch({ query: 'q' }, controller.signal);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.signal).toBe(controller.signal);
  });

  it('throws Unauthenticated on a 401 before streaming', async () => {
    mockFetch(401, null);
    await expect(streamSearch({ query: 'q' })).rejects.toBeInstanceOf(
      Unauthenticated,
    );
  });

  it('throws ApiError carrying the status on a 503', async () => {
    mockFetch(503, null);
    const err = await streamSearch({ query: 'q' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(503);
  });

  it('throws ApiError on any other non-OK status', async () => {
    mockFetch(500, null);
    const err = await streamSearch({ query: 'q' }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
  });

  it('returns the Response on success so the caller can read the body', async () => {
    mockFetch(200, streamFrom(['{"type":"result","seq":1,"result":{}}\n']));
    const response = await streamSearch({ query: 'q' });
    expect(response.ok).toBe(true);
    const events = await collect(parseNdjson(response.body));
    expect(events[0]?.type).toBe('result');
  });
});
