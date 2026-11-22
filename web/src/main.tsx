import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
// Import only the base declarations and the solid set — brands and regular are
// unused and add ~130 KB of woff2 font files to the bundle.
import '@fortawesome/fontawesome-free/css/fontawesome.min.css';
import '@fortawesome/fontawesome-free/css/solid.min.css';
import './styles/global.css';
import App from './App';
import { createQueryClient } from './queryClient';
import { ErrorBoundary } from './components/layout/ErrorBoundary/ErrorBoundary';

const queryClient = createQueryClient();

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
