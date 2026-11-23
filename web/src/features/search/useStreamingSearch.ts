/**
 * Drives the `POST /api/search/stream` NDJSON stream into UI state.
 *
 * A non-OK initial response is recorded with its HTTP status so `SearchPage`
 * can route it: 401 to login, 503 to "index not ready", anything else to the
 * error screen. Each run aborts the previous one, and frames from a superseded
 * run are dropped so a slow earlier stream never overwrites a newer one.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ApiError,
  parseNdjson,
  streamSearch,
  Unauthenticated,
} from '../../api/client';
import { queryKeys } from '../../api/hooks/keys';
import type {
  FilterRequest,
  MeResponse,
  PhaseRecord,
  SearchPhase,
  SearchResponse,
} from '../../api/types';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export interface StreamFailure {
  /** HTTP status of a failed initial response; absent for in-stream errors. */
  status?: number;
  message: string;
}

export interface StreamingSearchState {
  status: StreamStatus;
  /**
   * The query this state belongs to, so the page never flashes a superseded
   * query's answer for a new one.
   */
  query: string | null;
  /** Completed phases, in order. */
  phaseRecords: PhaseRecord[];
  activePhase: SearchPhase | null;
  result: SearchResponse | null;
  error: StreamFailure | null;
}

const INITIAL_STATE: StreamingSearchState = {
  status: 'idle',
  query: null,
  phaseRecords: [],
  activePhase: null,
  result: null,
  error: null,
};

type Action =
  | { type: 'start'; query: string }
  | { type: 'phaseStart'; phase: SearchPhase }
  | { type: 'phaseDone'; record: PhaseRecord }
  | { type: 'result'; result: SearchResponse }
  | { type: 'error'; error: StreamFailure };

function reducer(
  state: StreamingSearchState,
  action: Action,
): StreamingSearchState {
  switch (action.type) {
    case 'start':
      return {
        status: 'streaming',
        query: action.query,
        phaseRecords: [],
        activePhase: null,
        result: null,
        error: null,
      };
    case 'phaseStart':
      return { ...state, activePhase: action.phase };
    case 'phaseDone':
      // Clear the active phase so a finished row never shows "in progress" in
      // the gap before the next phase_start.
      return {
        ...state,
        activePhase: null,
        phaseRecords: [...state.phaseRecords, action.record],
      };
    case 'result':
      return {
        ...state,
        status: 'done',
        activePhase: null,
        result: action.result,
      };
    case 'error':
      // Keep phaseRecords so the partial trace shows what ran before the failure.
      return {
        ...state,
        status: 'error',
        activePhase: null,
        error: action.error,
      };
    default:
      return state;
  }
}

const UNAVAILABLE = 'The search is unavailable right now. Try again in a moment.';

function toFailure(err: unknown): StreamFailure {
  if (err instanceof Unauthenticated) {
    return { status: 401, message: err.message };
  }
  if (err instanceof ApiError) {
    // Without a server detail, a 5xx or a non-JSON 2xx has only generic text.
    const generic = err.detail === undefined && (err.status >= 500 || err.status < 400);
    return { status: err.status, message: generic ? UNAVAILABLE : err.message };
  }
  // fetch rejects with a TypeError when the network fails.
  if (err instanceof TypeError) {
    return { message: UNAVAILABLE };
  }
  return {
    message: err instanceof Error ? err.message : 'The search failed.',
  };
}

/**
 * The last finished search, kept in the query cache so Back from a preview shows
 * the answer again instead of paying for the same search twice. Sign-out clears
 * the cache, and the entry also names its user, so another user never sees it.
 */
const KEPT_QUERY_KEY = ['search', 'kept'] as const;

interface KeptSearch {
  userId: number;
  key: string;
  state: StreamingSearchState;
}

const searchKey = (query: string, filters: FilterRequest): string =>
  `${query}\u0000${JSON.stringify(filters)}`;

/** Router location state of a link back to the results, which shows the kept answer like Back. */
export const RETURN_TO_RESULTS = { returnToResults: true } as const;

export interface UseStreamingSearch {
  state: StreamingSearchState;
  /** Starts a search, cancelling any in-flight one. */
  run: (query: string, filters: FilterRequest) => void;
}

/**
 * Runs agentic searches as a live NDJSON stream. With `restore` (read on the
 * first render only), the signed-in user's last finished search is shown again
 * without searching, as when the page is reached by Back.
 */
export function useStreamingSearch(restore = false): UseStreamingSearch {
  const queryClient = useQueryClient();
  const currentUserId = (): number | undefined =>
    queryClient.getQueryData<MeResponse>(queryKeys.me())?.user.id;

  const [kept] = useState<KeptSearch | undefined>(() => {
    const entry = queryClient.getQueryData<KeptSearch>(KEPT_QUERY_KEY);
    return restore && entry?.userId === currentUserId() ? entry : undefined;
  });
  // Observing the entry while the page is mounted makes its garbage-collection
  // delay run from leaving the page rather than from when the answer finished.
  useQuery({
    queryKey: KEPT_QUERY_KEY,
    queryFn: () => Promise.reject(new Error('The kept search is only ever set.')),
    enabled: false,
  });
  const [state, dispatch] = useReducer(
    reducer,
    kept?.state ?? INITIAL_STATE,
  );

  // Refs, not state: changing them must not re-render, and the async loop
  // must read the latest value.
  const controllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const keyRef = useRef<string | null>(kept?.key ?? null);

  useEffect(() => {
    const userId = currentUserId();
    if (state.status === 'done' && keyRef.current !== null && userId !== undefined) {
      queryClient.setQueryData<KeptSearch>(KEPT_QUERY_KEY, {
        userId,
        key: keyRef.current,
        state,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, queryClient]);

  const run = useCallback((query: string, filters: FilterRequest): void => {
    const key = searchKey(query, filters);
    if (keyRef.current === key && stateRef.current.status === 'done') {
      return;
    }
    keyRef.current = key;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    const isCurrent = (): boolean =>
      runId === runIdRef.current && !controller.signal.aborted;

    dispatch({ type: 'start', query });

    void (async () => {
      try {
        const response = await streamSearch(
          { query, filters },
          controller.signal,
        );
        if (!isCurrent()) {
          return;
        }
        for await (const event of parseNdjson(response.body)) {
          if (!isCurrent()) {
            return;
          }
          switch (event.type) {
            case 'phase_start':
              dispatch({ type: 'phaseStart', phase: event.phase });
              break;
            case 'phase_done':
              // Drop the frame envelope (type, seq).
              dispatch({
                type: 'phaseDone',
                record: {
                  phase: event.phase,
                  label: event.label,
                  detail: event.detail,
                  tokens: event.tokens,
                  cost: event.cost,
                  ms: event.ms,
                },
              });
              break;
            case 'result':
              dispatch({ type: 'result', result: event.result });
              // The server records the search; refresh the idle screen's list.
              void queryClient.invalidateQueries({
                queryKey: queryKeys.recentSearches(),
              });
              return;
            case 'error':
              dispatch({
                type: 'error',
                error: {
                  // Same state as a 503 on the initial response.
                  ...(event.kind === 'index_not_ready' ? { status: 503 } : {}),
                  message: event.message,
                },
              });
              return;
            default:
              break;
          }
        }
        if (isCurrent()) {
          dispatch({
            type: 'error',
            error: { message: 'The search ended unexpectedly.' },
          });
        }
      } catch (err) {
        // A deliberate abort (supersede / unmount) is not a user-facing error.
        if (!isCurrent()) {
          return;
        }
        if (err instanceof DOMException && err.name === 'AbortError') {
          return;
        }
        dispatch({ type: 'error', error: toFailure(err) });
      }
    })();
  }, [queryClient]);

  // Abort on unmount so a late frame can't dispatch and the request is released.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { state, run };
}
