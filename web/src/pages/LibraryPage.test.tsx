import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import { LibraryPage } from './LibraryPage';

// AppNavBar drives useAuth/useLogout and React-Router; stub it so this test
// covers only that LibraryPage mounts the navbar + the screen.
vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <nav data-testid="app-nav-bar" />,
}));

// LibraryScreen drives api hooks; stub it to a marker.
vi.mock('../features/library/LibraryScreen/LibraryScreen', () => ({
  LibraryScreen: () => <div data-testid="library-screen" />,
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('LibraryPage', () => {
  it('renders the application navigation bar', () => {
    renderPage();
    expect(screen.getByTestId('app-nav-bar')).toBeInTheDocument();
  });

  it('renders the LibraryScreen', () => {
    renderPage();
    expect(screen.getByTestId('library-screen')).toBeInTheDocument();
  });
});
