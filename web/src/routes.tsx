/**
 * Route table for the SPA.
 *
 * A bootstrap gate resolves `GET /api/setup/status` then `GET /api/auth/me` on
 * load, and the route guards redirect accordingly:
 *   - setup needed            → /setup
 *   - setup done, no session  → /login
 *   - authenticated           → the app
 */

import React, { Suspense } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
// Eager: the entry-path pages hit on every load.
import { SearchPage } from './pages/SearchPage';
import { LoginPage } from './pages/LoginPage';
import { SetupPage } from './pages/SetupPage';
import { ErrorBoundary } from './components/layout/ErrorBoundary/ErrorBoundary';
// Lazy: rarely-hit routes, split into separate chunks.
const IndexPage = React.lazy(() =>
  import('./pages/IndexPage').then((m) => ({ default: m.IndexPage })),
);
const UsersPage = React.lazy(() =>
  import('./pages/UsersPage').then((m) => ({ default: m.UsersPage })),
);
const KeysPage = React.lazy(() =>
  import('./pages/KeysPage').then((m) => ({ default: m.KeysPage })),
);
const SettingsPage = React.lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const LibraryPage = React.lazy(() =>
  import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })),
);
const LibraryDocumentPage = React.lazy(() =>
  import('./pages/LibraryDocumentPage').then((m) => ({ default: m.LibraryDocumentPage })),
);
const DocumentPage = React.lazy(() =>
  import('./pages/DocumentPage').then((m) => ({ default: m.DocumentPage })),
);
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
  // Branch on success explicitly so an errored or user-less `me` never renders
  // protected UI.
  if (!meQuery.isSuccess || meQuery.data.user === undefined) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

/**
 * Admin-only route guard layered on `ProtectedRoute`: a non-admin is
 * redirected to `/`.
 *
 * A navigation convenience only — every admin endpoint is enforced
 * server-side.
 */
function RequireAdmin({ children }: { children: React.ReactElement }): React.ReactElement {
  return (
    <ProtectedRoute>
      <AdminGate>{children}</AdminGate>
    </ProtectedRoute>
  );
}

/**
 * The inner half of `RequireAdmin`, rendered only once `ProtectedRoute` has
 * confirmed a signed-in user. Reads the role from `useMe` and redirects a
 * non-admin to the app root.
 */
function AdminGate({ children }: { children: React.ReactElement }): React.ReactElement {
  const meQuery = useMe();
  if (meQuery.data?.user.role !== 'admin') {
    return <Navigate to="/" replace />;
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

  // Resolved regardless of loading state so hooks are called unconditionally.
  // The me query stays disabled while setup state is unknown or setup is needed.
  const setupNeeded = setupQuery.data?.needed === true;
  const meQuery = useMe({ enabled: !setupNeeded });

  // Wait for setup-status; me may still be loading and that is fine for /setup.
  if (setupQuery.isLoading) {
    return <FullPageLoading />;
  }

  if (setupNeeded) {
    return intent === 'setup' ? children : <Navigate to="/setup" replace />;
  }

  if (intent === 'setup') {
    return <Navigate to="/login" replace />;
  }

  // intent === 'login'. Render the form without waiting for `me`: after a
  // logout redirect the query is mid-refetch, and a loader would flash a blank
  // frame between sign-out and the form.
  if (meQuery.data?.user !== undefined) {
    return <Navigate to="/" replace />;
  }
  return children;
}

/**
 * Inner route body. Reads the pathname so the `ErrorBoundary` resets on
 * navigation, isolating per-route crashes without a full reload.
 */
function RoutesBody(): React.ReactElement {
  const location = useLocation();
  return (
    <ErrorBoundary resetKeys={[location.pathname]}>
      <Suspense fallback={<FullPageLoading />}>
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
          <Route
            path="/index"
            element={
              <ProtectedRoute>
                <IndexPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/library"
            element={
              <ProtectedRoute>
                <LibraryPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAdmin>
                <SettingsPage />
              </RequireAdmin>
            }
          />
          <Route
            path="/settings/users"
            element={
              <RequireAdmin>
                <UsersPage />
              </RequireAdmin>
            }
          />
          <Route
            path="/settings/keys"
            element={
              <RequireAdmin>
                <KeysPage />
              </RequireAdmin>
            }
          />
          {/* Unknown /settings/* sub-paths stay within Settings rather than
              bouncing to the Search home. */}
          <Route
            path="/settings/*"
            element={<Navigate to="/settings" replace />}
          />
          <Route
            path="/library/document/:id"
            element={
              <ProtectedRoute>
                <LibraryDocumentPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/document/:id"
            element={
              <ProtectedRoute>
                <DocumentPage />
              </ProtectedRoute>
            }
          />
          {/* Unknown paths fall back to the root, which re-resolves the gate. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}

/** Top-level route table. */
export function AppRoutes(): React.ReactElement {
  return <RoutesBody />;
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
