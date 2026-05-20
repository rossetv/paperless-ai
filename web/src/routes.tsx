/**
 * Route table for the Paperless AI search SPA.
 *
 * Routing is auth-gated: when `useAuth().authenticated` is false the user
 * sees `LoginPage`; when true they see `SearchPage`. There is currently only
 * one route (`/`) — new pages extend this table.
 *
 * Intentionally exempt from the `eslint-plugin-boundaries` layer rules (see
 * `boundaries/ignore` in eslint.config.js) because the route table is the
 * integration point that knowingly imports from multiple layers.
 */

import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { SearchPage } from './pages/SearchPage';
import { LoginPage } from './pages/LoginPage';
import { useAuth } from './hooks/useAuth';

/**
 * Top-level route table.
 *
 * Auth switch: a single `'/'` route renders `LoginPage` or `SearchPage`
 * depending on the `authenticated` flag in `AuthContext`. No redirect is
 * needed — swapping the rendered element is sufficient and avoids URL churn.
 */
export function AppRoutes(): React.ReactElement {
  const { authenticated } = useAuth();

  return (
    <Routes>
      <Route
        path="/"
        element={authenticated ? <SearchPage /> : <LoginPage />}
      />
    </Routes>
  );
}
