/**
 * TanStack Query hooks — the ONLY way the rest of the app calls the backend.
 *
 * All server state lives here; no component or feature calls `fetch` directly
 * (CODE_GUIDELINES §12.6). The hooks are built on `client.ts` which owns the
 * base URL, `credentials: 'include'`, and error normalisation.
 *
 * Allowed deps: @tanstack/react-query, client.ts, types.ts
 * (leaf module — CODE_GUIDELINES §12.3, never imports components/features/pages).
 */

import { useQuery, useMutation } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { search, getFacets, getStats, login } from './client';
import type {
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  StatusResponse,
  LoginRequest,
} from './types';

// ---------------------------------------------------------------------------
// Query key factory — keeps cache keys consistent and avoids magic strings
// ---------------------------------------------------------------------------

const queryKeys = {
  search: (req: SearchRequest) => ['search', req] as const,
  facets: () => ['facets'] as const,
  stats: () => ['stats'] as const,
} as const;

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

/**
 * Execute a semantic search query.
 *
 * Disabled when `query` is empty so the hook stays in `pending` state without
 * issuing a request — avoids a pointless round-trip on initial render.
 */
export function useSearch(
  req: SearchRequest,
): UseQueryResult<SearchResponse, Error> {
  return useQuery({
    queryKey: queryKeys.search(req),
    queryFn: () => search(req),
    enabled: req.query.trim().length > 0,
  });
}

/** Fetch taxonomy facets for the filter panel. */
export function useFacets(): UseQueryResult<FacetsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.facets(),
    queryFn: getFacets,
  });
}

/** Fetch index statistics. */
export function useStats(): UseQueryResult<StatsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.stats(),
    queryFn: getStats,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

/**
 * Login mutation — POST /api/auth/login.
 *
 * On success the server sets an `HttpOnly` session cookie; the caller receives
 * `{ status: 'ok' }`. On failure the mutation exposes `Unauthenticated` as the
 * error so the caller can display an "invalid key" message without a separate
 * `instanceof` check.
 */
export function useLogin(): UseMutationResult<StatusResponse, Error, LoginRequest> {
  return useMutation({
    mutationFn: login,
  });
}
