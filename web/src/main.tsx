/**
 * Application entry point.
 *
 * Wires the provider stack around `App`:
 *   1. `QueryClientProvider` — TanStack Query server state
 *   2. `BrowserRouter`       — React Router
 *
 * The `BrowserRouter` sits inside `QueryClientProvider` so auth-aware
 * mutations (the login form) have access to the query client.
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
import App from './App';
import { ErrorBoundary } from './components/layout/ErrorBoundary/ErrorBoundary';

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
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
