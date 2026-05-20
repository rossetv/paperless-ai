/**
 * Client-side authentication state.
 *
 * Holds a single boolean — `authenticated` — and two setters: `login()` and
 * `logout()`. This hook is pure React state; it does NOT call the API. The
 * actual login POST lives in the `LoginForm` feature, which calls `onSuccess`
 * → `useAuth().login()` once the server has set the session cookie.
 *
 * An `Unauthenticated` error from any API call drives `useAuth().logout()` in
 * the consuming page, routing the user back to `LoginPage`.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3, hooks allow: []).
 */

import React from 'react';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface AuthContextValue {
  authenticated: boolean;
  login: () => void;
  logout: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export interface AuthProviderProps {
  children: React.ReactNode;
}

/**
 * Provides auth state to the subtree.
 *
 * Wrap the application root (below `QueryClientProvider`, above `Routes`) with
 * this provider. The initial state is `authenticated: false` — the SPA always
 * starts at the login screen and the session cookie determines whether the
 * first API call succeeds or bounces the user back.
 */
export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [authenticated, setAuthenticated] = React.useState(false);

  const login = React.useCallback(() => setAuthenticated(true), []);
  const logout = React.useCallback(() => setAuthenticated(false), []);

  const value = React.useMemo(
    () => ({ authenticated, login, logout }),
    [authenticated, login, logout],
  );

  return React.createElement(AuthContext.Provider, { value }, children);
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Returns the current auth state and the login/logout setters.
 *
 * Must be called inside an `AuthProvider` — throws if the context is absent
 * so missing provider wiring fails loudly during development.
 */
export function useAuth(): AuthContextValue {
  const ctx = React.useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth must be used inside AuthProvider');
  }
  return ctx;
}
