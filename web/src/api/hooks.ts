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

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { search, getFacets, getStats, login, logout, me, setup, setupStatus, publicStats, getRecentSearches } from './client';
import type {
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  LoginRequest,
  LoginResponse,
  MeResponse,
  SetupRequest,
  SetupResponse,
  SetupStatus,
  PublicStats,
  RecentSearchesResponse,
} from './types';

// ---------------------------------------------------------------------------
// Query key factory — keeps cache keys consistent and avoids magic strings
// ---------------------------------------------------------------------------

const queryKeys = {
  search: (req: SearchRequest) => ['search', req] as const,
  facets: () => ['facets'] as const,
  stats: () => ['stats'] as const,
  me: () => ['auth', 'me'] as const,
  setupStatus: () => ['setup', 'status'] as const,
  publicStats: () => ['stats', 'public'] as const,
  recentSearches: () => ['recent-searches'] as const,
} as const;

/** The `me` query key — exported so `useAuth` and `ProtectedRoute` agree on it. */
export const ME_QUERY_KEY = ['auth', 'me'] as const;

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

/**
 * The signed-in user's recent-search history — GET /api/recent-searches.
 *
 * Drives the idle search screen's "Recent searches" strip. `retry: false` so
 * a 401 (session gone) resolves to an error state at once rather than
 * retrying; the idle screen treats any error as "no recent searches" and
 * simply omits the strip.
 */
export function useRecentSearches(): UseQueryResult<RecentSearchesResponse, Error> {
  return useQuery({
    queryKey: queryKeys.recentSearches(),
    queryFn: getRecentSearches,
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// Auth query hooks
// ---------------------------------------------------------------------------

/**
 * The current authenticated user — GET /api/auth/me.
 *
 * `useAuth` is built on this hook. `retry: false` so a 401 (not signed in)
 * resolves to an error state immediately rather than retrying.
 *
 * `staleTime: 0` — deliberately short (differs from the 60 s global default)
 * so a login or logout flips the auth state on the very next mount.
 *
 * `enabled` — pass `false` when setup is still needed to avoid a guaranteed-
 * useless 401 round-trip on every first-run page load.
 */
export function useMe({ enabled = true }: { enabled?: boolean } = {}): UseQueryResult<MeResponse, Error> {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: me,
    retry: false,
    staleTime: 0,
    enabled,
  });
}

/**
 * Whether first-run setup is still needed — GET /api/setup/status.
 *
 * Public; used by the bootstrap gate before the user is known. `retry: false`
 * so a transient failure does not stall the gate.
 *
 * `staleTime: 0` — intentionally short (same reasoning as `useMe`): the gate
 * must reflect a just-completed setup without a stale cache masking it.
 */
export function useSetupStatus(): UseQueryResult<SetupStatus, Error> {
  return useQuery({
    queryKey: queryKeys.setupStatus(),
    queryFn: setupStatus,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Minimal public splash counts — GET /api/stats/public.
 *
 * Used only by the login splash. `retry: false` and a callers-must-degrade
 * contract: the login screen omits the numbers when this errors.
 *
 * `staleTime: 60_000` — document counts change infrequently; one minute's
 * staleness is fine for an informational splash display. This differs from
 * the `staleTime: 0` on `useMe` / `useSetupStatus`, which are auth-critical.
 */
export function usePublicStats(): UseQueryResult<PublicStats, Error> {
  return useQuery({
    queryKey: queryKeys.publicStats(),
    queryFn: publicStats,
    retry: false,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

/**
 * Login mutation — POST /api/auth/login.
 *
 * On success the server sets an `HttpOnly` session cookie and the `me` query
 * is invalidated so `useAuth` re-resolves to the signed-in user. On failure
 * the mutation exposes `Unauthenticated` (401) or `ApiError` (403 suspended).
 */
export function useLogin(): UseMutationResult<LoginResponse, Error, LoginRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: login,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

/**
 * Logout mutation — POST /api/auth/logout.
 *
 * On success the `me` query cache is cleared so `useAuth` immediately reports
 * the user as signed out and the router sends them to `/login`.
 */
export function useLogout(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData(queryKeys.me(), undefined);
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

/**
 * First-run setup mutation — POST /api/setup.
 *
 * Creates the first admin account. On success the `setup-status` and `me`
 * queries are invalidated so the bootstrap gate re-resolves — the freshly
 * created admin is signed in by the same response's session cookie.
 * On failure: `ApiError` with status 403 (bad token) or 409 (already set up).
 */
export function useSetup(): UseMutationResult<SetupResponse, Error, SetupRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.setupStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}
