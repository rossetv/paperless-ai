import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { SearchPage } from './SearchPage';

vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => null,
}));

// Each screen is a stand-in with the real field's shape: a search input and a
// named submit button; the loading screen's input is disabled, as the real one is.
type Fields = { onSearch?: (q: string) => void; disabled?: boolean };
function Field({ onSearch, disabled = false }: Fields) {
  return (
    <>
      <input type="search" aria-label="field" disabled={disabled} defaultValue="" />
      <button type="button" onClick={() => onSearch?.('pill')}>
        pill
      </button>
      <button type="button" aria-label="Search" onClick={() => onSearch?.('bills')}>
        go
      </button>
    </>
  );
}
vi.mock('../features/search/IdleScreen/IdleScreen', () => ({
  IdleScreen: (p: Fields) => <Field {...p} />,
}));
vi.mock('../features/search/LoadingScreen/LoadingScreen', () => ({
  LoadingScreen: () => <Field disabled />,
}));
vi.mock('../features/search/ResultsScreen/ResultsScreen', () => ({
  ResultsScreen: (p: Fields) => <Field {...p} />,
}));
vi.mock('../features/search/NoResultsScreen/NoResultsScreen', () => ({
  NoResultsScreen: () => null,
}));
vi.mock('../features/search/IndexNotReadyScreen/IndexNotReadyScreen', () => ({
  IndexNotReadyScreen: () => null,
}));
vi.mock('../features/search/SearchErrorScreen/SearchErrorScreen', () => ({
  SearchErrorScreen: () => null,
}));
vi.mock('../api/hooks', () => ({ ME_QUERY_KEY: ['auth', 'me'] }));

let streamState: Record<string, unknown> = {};
vi.mock('../features/search/useStreamingSearch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/search/useStreamingSearch')>()),
  useStreamingSearch: () => ({ state: streamState, run: vi.fn() }),
}));

const RESULT = { outcome_kind: 'answered', sources: [] };

function tree() {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('SearchPage focus', () => {
  it('returns focus to the search field once the results of a submitted search appear', async () => {
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: null, result: null, error: null };
    const { rerender } = render(tree());
    await userEvent.click(screen.getByRole('searchbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    // Searching: the field is disabled and cannot hold focus.
    expect(screen.getByRole('searchbox')).toBeDisabled();

    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(screen.getByRole('searchbox')).toHaveFocus();
  });

  it('does not take focus when the search was started from outside the field', async () => {
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: null, result: null, error: null };
    const { rerender } = render(tree());
    await userEvent.click(screen.getByRole('button', { name: 'pill' }));
    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(screen.getByRole('searchbox')).not.toHaveFocus();
  });
});
