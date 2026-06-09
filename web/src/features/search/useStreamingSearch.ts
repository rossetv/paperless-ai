/**
 * `useStreamingSearch` — drives the live NDJSON search stream into UI state.
 *
 * A `useReducer` over the search lifecycle. `run(query, filters)` opens a
 * `POST /api/search/stream`, then dispatches one action per decoded frame:
 *
 *   - `phase_start` → mark that phase active (the rail shows it "in progress");
 *   - `phase_done`  → append the completed `PhaseRecord` (tokens/cost/detail);
 *   - `result`      → the terminal success frame → `done`, store the response;
 *   - `error`       → an in-stream failure frame → `error`, keep partial records.
 *
 * A non-OK *initial* HTTP response (the stream never opens) throws from
 * `streamSearch` — `Unauthenticated` (401) or `ApiError` (status). The hook
 * catches it and records `error.status` so `SearchPage` can reproduce the
 * existing behaviour: 401 → invalidate `me` → login redirect; 503 → the
 * "index not ready" screen; anything else → the generic error screen.
 *
 * Cancellation: each `run` aborts any prior in-flight stream via an
 * `AbortController`, and the effect aborts the live stream on unmount. A run is
 * tagged with a monotonically-increasing id; a frame from a superseded (or
 * unmounted) run is dropped, so a slow earlier stream can never overwrite a
 * newer one's state.
 *
 * Allowed deps: react, api/client, api/types (CODE_GUIDELINES §12.3).
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

/** The lifecycle status of a streaming search. */
export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

/** A typed error surfaced to the UI; `status` is the HTTP code when known. */
export interface StreamFailure {
  /** The HTTP status of a failed *initial* response (401, 503, …), if any. */
  status?: number;
  /** A human-readable message for the error screen. */
  message: string;
}

/** The reducer state exposed to the page. */
export interface StreamingSearchState {
  status: StreamStatus;
  /** Completed phases, in order — drives the live rail and the trace panel. */
  phaseRecords: PhaseRecord[];
  /** The phase currently running, or null when none is mid-flight. */
  activePhase: SearchPhase | null;
  /** The final response once the stream completes; null until then. */
  result: SearchResponse | null;
  /** The failure once the stream errors; null otherwise. */
  error: StreamFailure | null;
}

const INITIAL_STATE: StreamingSearchState = {
  status: 'idle',
  phaseRecords: [],
  activePhase: null,
  result: null,
  error: null,
};

type Action =
  | { type: 'start' }
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
      // A fresh run wipes the prior trace so a stale rail never lingers.
      return {
        status: 'streaming',
        phaseRecords: [],
        activePhase: null,
        result: null,
        error: null,
      };
    case 'phaseStart':
      return { ...state, activePhase: action.phase };
    case 'phaseDone':
      // The phase that just finished is no longer the active one; the next
      // phase_start re-sets it. Clearing here keeps "in progress" off a
      // finished row in the gap before the next phase begins.
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
      // Keep phaseRecords so the partial trace still shows what ran before
      // failing.
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

/** Map a thrown initial-response error to a `StreamFailure`. */
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

export interface UseStreamingSearch {
  /** The current streaming state. */
  state: StreamingSearchState;
  /** Start a search; cancels any prior in-flight stream. */
  run: (query: string, filters: FilterRequest) => void;
}

/**
 * Run agentic searches as a live NDJSON stream.
 *
 * @returns The current `state` and a `run(query, filters)` starter.
 */
export function useStreamingSearch(): UseStreamingSearch {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

  // The controller for the live stream, and a monotonic id so a frame from a
  // superseded run is ignored. Refs (not state) — mutating them must not
  // re-render, and the async loop reads the latest value.
  const controllerRef = useRef<AbortController | null>(null);
  const runIdRef = useRef(0);

  const run = useCallback((query: string, filters: FilterRequest): void => {
    // Cancel any prior in-flight stream and supersede its run id.
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const runId = runIdRef.current + 1;
    runIdRef.current = runId;

    /** True while this run is still the active, un-aborted one. */
    const isCurrent = (): boolean =>
      runId === runIdRef.current && !controller.signal.aborted;

    dispatch({ type: 'start' });

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
              // Strip the frame envelope (type, seq) down to a PhaseRecord.
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

  // Abort the live stream on unmount so a late frame can't dispatch into an
  // unmounted tree, and the network request is released.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort();
    };
  }, []);

  return { state, run };
}
