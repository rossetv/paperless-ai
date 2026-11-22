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
import { ApiError, Unauthenticated } from './api/client';
import { useRouteAnnounce } from './hooks/useRouteAnnounce';

/** Renders nothing; lives inside Suspense so it acts once the new page has rendered. */
function RouteAnnouncer({ fallback }: { fallback: React.RefObject<HTMLElement | null> }): null {
  useRouteAnnounce(fallback);
  return null;
}

/**
 * Whether `me` names a signed-in user. A failed re-check (offline, 5xx, abort)
 * keeps the last known user; only a 401 or 403 (suspended account) signs them out.
 */
function isSignedIn(meQuery: ReturnType<typeof useMe>): boolean {
  if (meQuery.data?.user === undefined) return false;
  if (meQuery.isSuccess) return true;
  const { error } = meQuery;
  const refused = error instanceof Unauthenticated || (error instanceof ApiError && error.status === 403);
  return meQuery.isError && !refused;
}

/**
 * Wraps the protected app. Resolves auth via `useMe`:
 *  - while loading → the bootstrap loader
 *  - on a 401 / no user → redirect to `/login`
 *  - authenticated → render `children`
 *
 * Setup-status is checked one level up by `AppRoutes`, so by the time a
 * `ProtectedRoute` renders, setup is known to be complete.
 */
function ProtectedRoute({ children }: { children: React.ReactElement }): React.ReactElement {
  const meQuery = useMe();
  const location = useLocation();

  if (meQuery.isLoading) {
    return <FullPageLoading />;
  }
  // A user-less or 401'd `me` never renders protected UI.
  if (!isSignedIn(meQuery)) {
    const from = location.pathname + location.search + location.hash;
    return <Navigate to="/login" replace state={{ from }} />;
  }
  return children;
}

/**
 * Where to send a signed-in user who lands on `/login`: the page the guard
 * bounced them from, if router state names an in-app path, else the root.
 * A backslash is refused because browsers read `/\` like `//`.
 */
export function returnTarget(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  if (
    typeof from === 'string' &&
    from.startsWith('/') &&
    !from.includes('\\') &&
    !from.startsWith('//') &&
    !/^\/login(?:[/?#]|$)/.test(from)
  ) {
    return from;
  }
  return '/';
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
  const location = useLocation();

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
  if (isSignedIn(meQuery)) {
    return <Navigate to={returnTarget(location.state)} replace />;
  }
  return children;
}

/**
 * Inner route body. Reads the pathname so the `ErrorBoundary` resets on
 * navigation, isolating per-route crashes without a full reload.
 */
function RoutesBody(): React.ReactElement {
  const location = useLocation();
  const content = React.useRef<HTMLDivElement>(null);
  return (
    <ErrorBoundary resetKeys={[location.pathname]}>
      <Suspense fallback={<FullPageLoading />}>
        <div ref={content} tabIndex={-1} style={{ outline: 'none' }}>
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
        </div>
        <RouteAnnouncer fallback={content} />
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
