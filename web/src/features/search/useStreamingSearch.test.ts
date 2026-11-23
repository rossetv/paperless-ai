import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createElement, type ReactNode } from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PhaseRecord, SearchResponse, StreamEvent } from '../../api/types';

// Mock both halves of the streaming client so tests drive the event sequence.
vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return {
    ...actual,
    streamSearch: vi.fn(),
    parseNdjson: vi.fn(),
  };
});

import { streamSearch, parseNdjson, ApiError, Unauthenticated } from '../../api/client';
import { useStreamingSearch } from './useStreamingSearch';

const mockStreamSearch = streamSearch as ReturnType<typeof vi.fn>;
const mockParseNdjson = parseNdjson as ReturnType<typeof vi.fn>;

const EMPTY_FILTERS = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

function eventsGen(events: StreamEvent[]): AsyncGenerator<StreamEvent> {
  return (async function* () {
    for (const ev of events) {
      yield ev;
    }
  })();
}

/** A hung stream that never produces a frame. */
function neverGen(): AsyncGenerator<StreamEvent> {
  return (async function* () {
    await new Promise<void>(() => {}); // never resolves
    yield undefined as never; // unreachable — satisfies require-yield
  })();
}

function makeResponse(answer: string): SearchResponse {
  return {
    answer,
    sources: [],
    plan: { specs: [] },
    stats: { llm_calls: 1, latency_ms: 10, refined: false },
    trace: { phases: [] },
    cost: {
      tokens: { prompt: 0, completion: 0, reasoning: 0, total: 0 },
      usd: 0,
      local: false,
      llm_calls: 1,
    },
    outcome_kind: 'answered',
  };
}

const PLAN_START: StreamEvent = {
  type: 'phase_start',
  seq: 1,
  phase: 'plan',
  label: 'Planning the query',
};
const PLAN_DONE: StreamEvent & PhaseRecord = {
  type: 'phase_done',
  seq: 2,
  phase: 'plan',
  label: 'Planning the query',
  detail: { rewritten_query: 'npower bills 2024' },
  tokens: { prompt: 10, completion: 5, reasoning: 0, total: 15 },
  cost: { usd: 0.0001, local: false },
  ms: 42,
};

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(QueryClientProvider, { client }, children);

function signIn(id: number): void {
  client.setQueryData(['auth', 'me'], { user: { id } });
}

describe('useStreamingSearch', () => {
  beforeEach(() => {
    mockStreamSearch.mockReset();
    mockParseNdjson.mockReset();
    client = new QueryClient();
    signIn(1);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts idle', () => {
    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.phaseRecords).toEqual([]);
    expect(result.current.state.result).toBeNull();
    expect(result.current.state.error).toBeNull();
  });

  it('transitions idle → streaming → done, accumulating phase records', async () => {
    const response = makeResponse('answered');
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(
      eventsGen([
        PLAN_START,
        PLAN_DONE,
        { type: 'result', seq: 3, result: response },
      ]),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });

    await act(async () => {
      result.current.run('npower bills', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('done'));
    expect(result.current.state.result).toEqual(response);
    expect(result.current.state.phaseRecords).toHaveLength(1);
    expect(result.current.state.phaseRecords[0]?.phase).toBe('plan');
    expect(result.current.state.activePhase).toBeNull();
  });

  it('sets the active phase from phase_start before the record lands', async () => {
    let release!: () => void;
    const gate = new Promise<void>((res) => {
      release = res;
    });
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(
      (async function* () {
        yield PLAN_START;
        await gate; // hold the stream open after the start frame
        yield PLAN_DONE;
      })(),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.activePhase).toBe('plan'));
    expect(result.current.state.status).toBe('streaming');
    expect(result.current.state.phaseRecords).toHaveLength(0);

    await act(async () => {
      release();
    });
    await waitFor(() =>
      expect(result.current.state.phaseRecords).toHaveLength(1),
    );
  });

  it('transitions to error on an in-stream error frame, keeping partial records', async () => {
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(
      eventsGen([
        PLAN_START,
        PLAN_DONE,
        { type: 'error', seq: 3, kind: 'internal', message: 'search failed' },
      ]),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.error?.message).toBe('search failed');
    expect(result.current.state.phaseRecords).toHaveLength(1);
  });

  it('invalidates the recent searches when a result arrives', async () => {
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(
      eventsGen([{ type: 'result', seq: 1, result: makeResponse('ok') }]),
    );
    client.setQueryData(['recent-searches'], { searches: [] });
    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('done'));
    expect(client.getQueryState(['recent-searches'])?.isInvalidated).toBe(true);
  });

  it('maps an in-stream index_not_ready frame to the 503 status', async () => {
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(
      eventsGen([
        {
          type: 'error',
          seq: 1,
          kind: 'index_not_ready',
          message: 'The search index is not ready',
        },
      ]),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.error?.status).toBe(503);
  });

  it('surfaces a 401 from streamSearch with the status on the error', async () => {
    mockStreamSearch.mockRejectedValue(new Unauthenticated());

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.error?.status).toBe(401);
  });

  it('surfaces a 503 from streamSearch with the status on the error', async () => {
    mockStreamSearch.mockRejectedValue(new ApiError(503));

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.error?.status).toBe(503);
  });

  describe('failure wording', () => {
    const SENTENCE = 'The search is unavailable right now. Try again in a moment.';

    async function failWith(err: unknown) {
      mockStreamSearch.mockRejectedValue(err);
      const { result } = renderHook(() => useStreamingSearch(), { wrapper });
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      await waitFor(() => expect(result.current.state.status).toBe('error'));
      return result.current.state.error;
    }

    it('shows a plain sentence for a 5xx without a server detail', async () => {
      expect((await failWith(new ApiError(500)))?.message).toBe(SENTENCE);
    });

    it('shows a plain sentence for a non-JSON response', async () => {
      const error = await failWith(new ApiError(200, 'Server returned a non-JSON response'));
      expect(error?.message).toBe(SENTENCE);
    });

    it('shows a plain sentence when the network fails', async () => {
      expect((await failWith(new TypeError('Failed to fetch')))?.message).toBe(SENTENCE);
    });

    it('does not hide a TypeError thrown while the stream is read', async () => {
      mockStreamSearch.mockResolvedValue({ body: {} } as Response);
      mockParseNdjson.mockImplementation(() => {
        throw new TypeError('x is not a function');
      });
      const { result } = renderHook(() => useStreamingSearch(), { wrapper });
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      await waitFor(() => expect(result.current.state.status).toBe('error'));
      expect(result.current.state.error?.message).toBe('x is not a function');
    });

    it('keeps the server detail when it sent one', async () => {
      const error = await failWith(new ApiError(500, undefined, 'Paperless is down'));
      expect(error?.message).toBe('Paperless is down');
    });

    it('leaves a 4xx message as it is', async () => {
      expect((await failWith(new ApiError(404)))?.message).toBe('API error 404');
    });
  });

  it('goes to the error state when the stream ends without a result or error', async () => {
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(eventsGen([PLAN_START, PLAN_DONE]));

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('error'));
    expect(result.current.state.error?.message).toBe(
      'The search ended unexpectedly.',
    );
    expect(result.current.state.phaseRecords).toHaveLength(1);
  });

  describe('keeping the last finished search', () => {
    async function finishSearch(query: string): Promise<void> {
      mockStreamSearch.mockResolvedValue({ body: {} } as Response);
      mockParseNdjson.mockReturnValueOnce(
        eventsGen([{ type: 'result', seq: 1, result: makeResponse('kept') }]),
      );
      const first = renderHook(() => useStreamingSearch(), { wrapper });
      await act(async () => {
        first.result.current.run(query, EMPTY_FILTERS);
      });
      await waitFor(() => expect(first.result.current.state.status).toBe('done'));
      first.unmount();
      mockStreamSearch.mockClear();
    }

    it('shows the kept answer on remount and does not search again', async () => {
      await finishSearch('q');

      const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
      expect(result.current.state.status).toBe('done');
      expect(result.current.state.result?.answer).toBe('kept');
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      expect(mockStreamSearch).not.toHaveBeenCalled();
      expect(result.current.state.status).toBe('done');
    });

    describe('how long the kept answer lasts', () => {
      const MINUTE = 60_000;

      async function stayOnAnswerThenLeave(stayMinutes: number) {
        mockStreamSearch.mockResolvedValue({ body: {} } as Response);
        mockParseNdjson.mockReturnValueOnce(
          eventsGen([{ type: 'result', seq: 1, result: makeResponse('kept') }]),
        );
        const page = renderHook(() => useStreamingSearch(), { wrapper });
        await act(async () => {
          page.result.current.run('q', EMPTY_FILTERS);
        });
        await waitFor(() => expect(page.result.current.state.status).toBe('done'));
        await act(async () => {
          vi.advanceTimersByTime(stayMinutes * MINUTE);
        });
        page.unmount();
        mockStreamSearch.mockClear();
      }

      beforeEach(() => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
      });
      afterEach(() => {
        vi.useRealTimers();
      });

      it('counts from leaving the page, not from when the answer finished', async () => {
        await stayOnAnswerThenLeave(7);
        await act(async () => {
          vi.advanceTimersByTime(4 * MINUTE);
        });

        const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
        expect(result.current.state.status).toBe('done');
      });

      it('is dropped once the user has been away longer than that', async () => {
        await stayOnAnswerThenLeave(7);
        await act(async () => {
          vi.advanceTimersByTime(6 * MINUTE);
        });

        const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
        expect(result.current.state.status).toBe('idle');
      });
    });

    it('searches for a different query or different filters', async () => {
      await finishSearch('q');
      mockParseNdjson.mockImplementation(() => neverGen());

      const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
      await act(async () => {
        result.current.run('other', EMPTY_FILTERS);
      });
      expect(mockStreamSearch).toHaveBeenCalledTimes(1);
      await act(async () => {
        result.current.run('other', { ...EMPTY_FILTERS, tag_ids: [3] });
      });
      expect(mockStreamSearch).toHaveBeenCalledTimes(2);
    });

    it('searches again when the page was not reached by Back', async () => {
      await finishSearch('q');
      mockParseNdjson.mockReturnValueOnce(neverGen());

      const { result } = renderHook(() => useStreamingSearch(false), { wrapper });
      expect(result.current.state.status).toBe('idle');
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      expect(mockStreamSearch).toHaveBeenCalledTimes(1);
    });

    it('does not show the kept answer to another user', async () => {
      await finishSearch('q');
      signIn(2);
      mockParseNdjson.mockReturnValueOnce(neverGen());

      const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
      expect(result.current.state.status).toBe('idle');
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      expect(mockStreamSearch).toHaveBeenCalledTimes(1);
    });

    it('does not show the kept answer after the cache is cleared at sign-out', async () => {
      await finishSearch('q');
      client.clear();
      signIn(1);

      const { result } = renderHook(() => useStreamingSearch(true), { wrapper });
      expect(result.current.state.status).toBe('idle');
    });

    it('does not keep a failed search, so Try again runs', async () => {
      mockStreamSearch.mockResolvedValue({ body: {} } as Response);
      mockParseNdjson.mockReturnValueOnce(
        eventsGen([{ type: 'error', seq: 1, kind: 'internal', message: 'boom' }]),
      );
      const first = renderHook(() => useStreamingSearch(), { wrapper });
      await act(async () => {
        first.result.current.run('q', EMPTY_FILTERS);
      });
      await waitFor(() => expect(first.result.current.state.status).toBe('error'));
      first.unmount();
      mockStreamSearch.mockClear();
      mockParseNdjson.mockReturnValueOnce(neverGen());

      const { result } = renderHook(() => useStreamingSearch(), { wrapper });
      expect(result.current.state.status).toBe('idle');
      await act(async () => {
        result.current.run('q', EMPTY_FILTERS);
      });
      expect(mockStreamSearch).toHaveBeenCalledTimes(1);
    });
  });

  it('aborts a prior in-flight stream when run is called again', async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort');

    // First run: a stream that never resolves its events.
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValueOnce(neverGen());
    // Second run: completes immediately.
    const response = makeResponse('second');
    mockParseNdjson.mockReturnValueOnce(
      eventsGen([{ type: 'result', seq: 1, result: response }]),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('first', EMPTY_FILTERS);
    });
    await act(async () => {
      result.current.run('second', EMPTY_FILTERS);
    });

    await waitFor(() => expect(result.current.state.status).toBe('done'));
    expect(result.current.state.result?.answer).toBe('second');
    expect(abortSpy).toHaveBeenCalled();
  });

  it('does not dispatch from an aborted run that resolves late', async () => {
    // First run yields a result only AFTER a gate we release post-second-run.
    let release!: () => void;
    const gate = new Promise<void>((res) => {
      release = res;
    });
    const stale = makeResponse('stale');
    const fresh = makeResponse('fresh');

    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValueOnce(
      (async function* () {
        await gate;
        yield { type: 'result', seq: 1, result: stale };
      })(),
    );
    mockParseNdjson.mockReturnValueOnce(
      eventsGen([{ type: 'result', seq: 1, result: fresh }]),
    );

    const { result } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('first', EMPTY_FILTERS);
    });
    await act(async () => {
      result.current.run('second', EMPTY_FILTERS);
    });
    await waitFor(() => expect(result.current.state.result?.answer).toBe('fresh'));

    // Release the stale run — its result must be ignored.
    await act(async () => {
      release();
      await Promise.resolve();
    });
    expect(result.current.state.result?.answer).toBe('fresh');
  });

  it('aborts the in-flight stream on unmount', async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort');
    mockStreamSearch.mockResolvedValue({ body: {} } as Response);
    mockParseNdjson.mockReturnValue(neverGen());

    const { result, unmount } = renderHook(() => useStreamingSearch(), { wrapper });
    await act(async () => {
      result.current.run('q', EMPTY_FILTERS);
    });
    unmount();
    expect(abortSpy).toHaveBeenCalled();
  });
});
