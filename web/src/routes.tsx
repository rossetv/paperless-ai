/**
 * Route table for the Paperless AI SPA.
 *
 * Real React-Router routes replace the former render-swap:
 *   - `/setup` — first-run setup, shown only while no users exist
 *   - `/login` — sign-in, shown only when unauthenticated
 *   - `/`      — the search app, protected
 *
 * A bootstrap gate resolves two server queries on load — `GET
 * /api/setup/status` then `GET /api/auth/me` — and the route guards below
 * redirect accordingly:
 *   - setup needed            → /setup
 *   - setup done, no session  → /login
 *   - authenticated           → the app
 *
 * `ProtectedRoute` and `BootstrapGate` live here because the `app` tier is
 * the only layer permitted to import pages + api + hooks together
 * (CODE_GUIDELINES §12.3 / eslint.config.js).
 *
 * Classified as the `app` element type in `eslint-plugin-boundaries`.
 */

import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { SearchPage } from './pages/SearchPage';
import { LoginPage } from './pages/LoginPage';
import { SetupPage } from './pages/SetupPage';
import { FullPageLoading } from './components/layout/FullPageLoading/FullPageLoading';
import { useSetupStatus, useMe } from './api/hooks';

/**
 * Wraps the protected app. Resolves auth via `useMe`:
 *  - while loading → the bootstrap loader
 *  - on error / no user → redirect to `/login`
 *  - authenticated → render `children`
 *
 * Setup-status is checked one level up by `AppRoutes`, so by the time a
 * `ProtectedRoute` renders, setup is known to be complete.
 */
function ProtectedRoute({ children }: { children: React.ReactElement }): React.ReactElement {
  const meQuery = useMe();

  if (meQuery.isLoading) {
    return <FullPageLoading />;
  }
  // Branch explicitly on query success — guards against silently rendering
  // protected UI if the me query errors or returns without a user.
  if (!meQuery.isSuccess || meQuery.data.user === undefined) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

/**
 * Bootstrap gate for the `/login` and `/setup` routes.
 *
 * `intent` is the route's purpose:
 *  - `'setup'` — only valid while setup is needed; otherwise redirect to `/`
 *  - `'login'` — only valid when setup is done AND unauthenticated
 *
 * Redirect precedence (both routes): setup-needed wins over everything; then
 * an authenticated user is bounced to the app; otherwise the page renders.
 */
function BootstrapGate({
  intent,
  children,
}: {
  intent: 'setup' | 'login';
  children: React.ReactElement;
}): React.ReactElement {
  const setupQuery = useSetupStatus();

  // Resolve setup-needed from query data regardless of loading state so hooks
  // are called unconditionally. `undefined` while still loading — treated as
  // "not yet known", which disables the me query (no point hitting /api/auth/me
  // while setup state is unknown or while setup is actively required).
  const setupNeeded = setupQuery.data?.needed === true;
  const meQuery = useMe({ enabled: !setupNeeded });

  // Wait for setup-status; me may still be loading and that is fine for /setup.
  if (setupQuery.isLoading) {
    return <FullPageLoading />;
  }

  if (setupNeeded) {
    // Only the setup page is reachable until the first admin exists.
    return intent === 'setup' ? children : <Navigate to="/setup" replace />;
  }

  // Setup is complete — /setup is no longer valid.
  if (intent === 'setup') {
    return <Navigate to="/login" replace />;
  }

  // intent === 'login' — bounce an already-authenticated user to the app.
  if (meQuery.isLoading) {
    return <FullPageLoading />;
  }
  if (meQuery.data?.user !== undefined) {
    return <Navigate to="/" replace />;
  }
  return children;
}

/**
 * Top-level route table.
 *
 * `/` resolves through `BootstrapGate` semantics inside `ProtectedRoute`
 * plus an explicit setup check, so a fresh install lands on `/setup`, a
 * signed-out user on `/login`, and a signed-in user on `SearchPage`.
 */
export function AppRoutes(): React.ReactElement {
  return (
    <Routes>
      <Route
        path="/setup"
        element={
          <BootstrapGate intent="setup">
            <SetupPage />
          </BootstrapGate>
        }
      />
      <Route
        path="/login"
        element={
          <BootstrapGate intent="login">
            <LoginPage />
          </BootstrapGate>
        }
      />
      <Route
        path="/"
        element={
          <RootRoute />
        }
      />
      {/* Unknown paths fall back to the root, which re-resolves the gate. */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

/**
 * The `/` route. Setup-status is checked first (a fresh install must reach
 * `/setup` even before any session exists), then `ProtectedRoute` enforces
 * authentication.
 */
function RootRoute(): React.ReactElement {
  const setupQuery = useSetupStatus();

  if (setupQuery.isLoading) {
    return <FullPageLoading />;
  }
  if (setupQuery.data?.needed === true) {
    return <Navigate to="/setup" replace />;
  }
  return (
    <ProtectedRoute>
      <SearchPage />
    </ProtectedRoute>
  );
}
