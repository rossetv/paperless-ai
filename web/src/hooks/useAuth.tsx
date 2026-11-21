/**
 * Client-side authentication state: a read-only view over the `useMe` query
 * (GET /api/auth/me). The server session is the source of truth.
 *
 * Sign-in and sign-out live in the `useLogin` / `useLogout` mutations, which
 * invalidate `me` so this hook re-resolves.
 */

import type { User } from '../api/types';
import { useMe } from '../api/hooks';

/** The authenticated-session view returned by `useAuth`. */
export interface AuthState {
  /** The current user, or `null` when unauthenticated or still loading. */
  user: User | null;
  /** The current user's role, or `null` when there is no user. */
  role: User['role'] | null;
  /** True once `me` has resolved to a real user. */
  isAuthenticated: boolean;
  /** True while the first `me` request is in flight (auth state unknown). */
  isLoading: boolean;
}

/**
 * Returns the current authentication state, derived from `useMe`.
 *
 * Must be called inside a `QueryClientProvider` (every page already is). When
 * `me` errors — typically a 401 — the user is reported as unauthenticated.
 */
export function useAuth(): AuthState {
  const meQuery = useMe();
  const user = meQuery.data?.user ?? null;

  return {
    user,
    role: user?.role ?? null,
    isAuthenticated: user !== null,
    isLoading: meQuery.isLoading,
  };
}
