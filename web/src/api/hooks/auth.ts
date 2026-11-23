/** Auth hooks: login, logout, me, setup and public stats. */

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

/** Marks requests whose 401 is an answer, not a lapsed session; the query client skips its session re-check. */
const skipSessionCheck = { skipSessionCheck: true };

/** Cached queries a sign-in leaves alone, as joined keys. */
const KEPT_ON_LOGIN: ReadonlySet<string> = new Set(
  [queryKeys.me(), queryKeys.setupStatus(), queryKeys.publicStats()].map((key) => key.join('/')),
);

/**
 * The current authenticated user — GET /api/auth/me. `useAuth` is built on it.
 *
 * `retry: false` so a 401 resolves to an error at once; `staleTime: 0` so a
 * login or logout flips the auth state on the next mount. Pass `enabled: false`
 * while setup is still needed to skip a certain 401.
 */
export function useMe({ enabled = true }: { enabled?: boolean } = {}): UseQueryResult<MeResponse, Error> {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: me,
    meta: skipSessionCheck,
    retry: false,
    staleTime: 0,
    enabled,
  });
}

/**
 * Whether first-run setup is still needed — GET /api/setup/status.
 *
 * Used by the bootstrap gate. `retry: false` so a failure does not stall it;
 * `staleTime: 0` so a just-completed setup is never masked by the cache.
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
 * Public splash counts for the login screen — GET /api/stats/public.
 *
 * The login screen omits the numbers when this errors. A minute's staleness is
 * fine here, unlike the auth-critical `useMe` / `useSetupStatus`.
 */
export function usePublicStats(): UseQueryResult<PublicStats, Error> {
  return useQuery({
    queryKey: queryKeys.publicStats(),
    queryFn: publicStats,
    retry: false,
    staleTime: 60_000,
  });
}

/**
 * Login mutation — POST /api/auth/login. Clears the earlier session's cached data and
 * invalidates `me` so `useAuth` re-resolves.
 *
 * Fails with `Unauthenticated` (401) or `ApiError` (403, suspended account).
 */
export function useLogin(): UseMutationResult<LoginResponse, Error, LoginRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: login,
    meta: skipSessionCheck,
    onSuccess: () => {
      // A lapsed session leaves its cached data behind and the next sign-in may be
      // another user, so drop all of it. `me` stays, to be re-checked below; the
      // setup status and public stats are not per-user, and the sign-in gate needs them.
      queryClient.removeQueries({
        predicate: (query) => !KEPT_ON_LOGIN.has(query.queryKey.join('/')),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

/** Logout mutation — POST /api/auth/logout. Clears the whole query cache on settle. */
export function useLogout(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    meta: skipSessionCheck,
    // onSettled, not onSuccess: AppNavBar goes to /login either way, and a stale
    // `me` entry after a failed logout would bounce that redirect back into the app.
    onSettled: () => {
      // Clear everything, not just `me`, so the next user on a shared machine
      // never sees the previous session's cached data.
      queryClient.clear();
    },
  });
}

/**
 * First-run setup mutation — POST /api/setup; creates the first admin.
 *
 * The response's session cookie signs the new admin in, so `setup-status` and
 * `me` are invalidated. Fails with `ApiError` 403 (bad token) or 409 (already set up).
 */
export function useSetup(): UseMutationResult<SetupResponse, Error, SetupRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setup,
    meta: skipSessionCheck,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.setupStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}
