import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';

/** Renders App with the minimal provider tree it requires. */
function renderApp(): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

describe('App', () => {
  it('renders the placeholder heading on the root route', () => {
    renderApp();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Paperless AI Search');
  });
});
