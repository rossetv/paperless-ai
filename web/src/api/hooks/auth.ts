/**
 * Auth query and mutation hooks — login, logout, me, setup, public stats.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  login,
  logout,
  me,
  setup,
  setupStatus,
  publicStats,
} from '../client';
import type {
  LoginRequest,
  LoginResponse,
  MeResponse,
  SetupRequest,
  SetupResponse,
  SetupStatus,
  PublicStats,
} from '../types';
import { queryKeys } from './keys';

// ---------------------------------------------------------------------------
// Query hooks
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
 * On settle the `me` query cache is cleared so `useAuth` immediately reports
 * the user as signed out and the router sends them to `/login`.
 */
export function useLogout(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    // onSettled (not onSuccess): clear the cache whether the request succeeded
    // or failed. AppNavBar navigates to /login regardless of outcome, so a
    // failed logout must still drop the cached user — otherwise the stale
    // "logged-in" me entry would bounce the /login redirect straight back into
    // the app. Fail-closed: a sign-out click always lands signed out locally.
    onSettled: () => {
      // Clear the entire query cache on logout so no stale data (documents,
      // library, settings, API keys, taxonomy, …) from the previous session
      // lingers and is visible to the next user within the staleTime window.
      // `clear()` is equivalent to removeQueries for every key — it wipes
      // both the me entry (which triggers the /login redirect) and all other
      // cached entries, preventing cross-user data leakage on shared machines.
      queryClient.clear();
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
