/**
 * Application entry point.
 *
 * Wires the provider stack around `App`:
 *   1. `QueryClientProvider` — TanStack Query server state
 *   2. `BrowserRouter`       — React Router
 *   3. `AuthProvider`        — client-side auth state (useAuth hook)
 *
 * The `BrowserRouter` sits outside `AuthProvider` so the router is available
 * to both auth-gated pages. `AuthProvider` sits inside `QueryClientProvider`
 * so auth-aware mutations (the login form) have access to the query client.
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
// Import only the base declarations and the solid set — brands and regular are
// unused and add ~130 KB of woff2 font files to the bundle.
import '@fortawesome/fontawesome-free/css/fontawesome.min.css';
import '@fortawesome/fontawesome-free/css/solid.min.css';
import './styles/global.css';
import { AuthProvider } from './hooks/useAuth';
import App from './App';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
      // Disable refetch on window focus — the LLM-backed /api/search is
      // expensive (up to 3 chained LLM calls) and re-billing on every
      // alt-tab is wasteful. Auth hooks use staleTime:0 + mount refetch
      // so login/logout state is unaffected by this setting.
      refetchOnWindowFocus: false,
    },
  },
});

const rootElement = document.getElementById('root');
if (rootElement === null) {
  throw new Error('Root element #root not found in the document');
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
