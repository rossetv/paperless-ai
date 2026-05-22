/**
 * Client-side authentication state.
 *
 * `useAuth` is a thin, read-only wrapper over the `useMe` react-query hook
 * (GET /api/auth/me). It does not own state — the source of truth is the
 * server session, cached by react-query. It exposes:
 *
 *   - `user`            — the current `User`, or `null` when not signed in
 *   - `role`            — the user's role, or `null`
 *   - `isAuthenticated` — true once `me` has resolved to a user
 *   - `isLoading`       — true while the first `me` request is in flight
 *
 * Sign-in and sign-out are NOT here: they are the `useLogin` / `useLogout`
 * mutations in `api/hooks.ts`, which invalidate the `me` query so this hook
 * re-resolves. A 401 from any call surfaces as `useMe` error → this hook
 * reports `isAuthenticated: false` and the router routes to `/login`.
 *
 * `AuthProvider` is retained as a transparent pass-through so existing
 * provider wiring in `main.tsx` and tests need not be torn out; it adds no
 * behaviour. New code does not need to wrap anything in it.
 *
 * Allowed deps: api/ + react (CODE_GUIDELINES §12.3 — hooks may import api).
 */

import React from 'react';
import type { User } from '../api/types';
import { useMe } from '../api/hooks';

// ---------------------------------------------------------------------------
// Hook return shape
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Provider — transparent pass-through (kept for wiring compatibility)
// ---------------------------------------------------------------------------

export interface AuthProviderProps {
  children: React.ReactNode;
}

/**
 * Transparent wrapper kept so existing `main.tsx` / test wiring still
 * compiles. It holds no state and adds no behaviour — auth state lives in
 * react-query. New code need not use it.
 */
export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  return <>{children}</>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

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
