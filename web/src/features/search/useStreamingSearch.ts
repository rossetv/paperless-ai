/**
 * Drives the `POST /api/search/stream` NDJSON stream into UI state.
 *
 * A non-OK initial response is recorded with its HTTP status so `SearchPage`
 * can route it: 401 to login, 503 to "index not ready", anything else to the
 * error screen. Each run aborts the previous one, and frames from a superseded
 * run are dropped so a slow earlier stream never overwrites a newer one.
 */

import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  ApiError,
  parseNdjson,
  streamSearch,
  Unauthenticated,
} from '../../api/client';
import type {
  FilterRequest,
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

function toFailure(err: unknown): StreamFailure {
  if (err instanceof Unauthenticated) {
    return { status: 401, message: err.message };
  }
  if (err instanceof ApiError) {
    return { status: err.status, message: err.message };
  }
  return {
    message: err instanceof Error ? err.message : 'The search failed.',
  };
}

/**
 * The last finished search, kept across unmounts so Back from a preview shows
 * the answer again instead of paying for the same search twice. In memory only:
 * a reload searches afresh.
 */
let lastDone: { key: string; state: StreamingSearchState } | null = null;

const searchKey = (query: string, filters: FilterRequest): string =>
  `${query}\u0000${JSON.stringify(filters)}`;

/** Forgets the kept search; for tests. */
export function clearLastSearch(): void {
  lastDone = null;
}

export interface UseStreamingSearch {
  state: StreamingSearchState;
  /** Starts a search, cancelling any in-flight one. */
  run: (query: string, filters: FilterRequest) => void;
}

/** Runs agentic searches as a live NDJSON stream. */
export function useStreamingSearch(): UseStreamingSearch {
  const [state, dispatch] = useReducer(
    reducer,
    lastDone?.state ?? INITIAL_STATE,
  );

  // Refs, not state: changing them must not re-render, and the async loop
  // must read the latest value.
  const controllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;
  const keyRef = useRef<string | null>(lastDone?.key ?? null);

  useEffect(() => {
    if (state.status === 'done' && keyRef.current !== null) {
      lastDone = { key: keyRef.current, state };
    }
  }, [state]);

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
              return;
            case 'error':
              dispatch({
                type: 'error',
                error: { message: event.message },
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
  }, []);

  // Abort on unmount so a late frame can't dispatch and the request is released.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { state, run };
}
