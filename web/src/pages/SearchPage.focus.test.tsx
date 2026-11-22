import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { SearchPage } from './SearchPage';

vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <button type="button">Account</button>,
}));

// Each screen is a stand-in with the real field's shape: a search input and a
// named submit button; the loading screen's input is disabled, as the real one is.
// A tag filter's search input comes first, as the filter panel's does.
type Fields = { onSearch?: (q: string) => void; disabled?: boolean };
function Field({ onSearch, disabled = false }: Fields) {
  return (
    <>
      <input type="search" id="filter-tags-search" aria-label="Search tags" />
      <input
        type="search"
        id="results-search"
        aria-label="What do you want to know?"
        disabled={disabled}
        defaultValue=""
      />
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
    const field = () => screen.getByRole('searchbox', { name: 'What do you want to know?' });
    await userEvent.click(field());
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    // Searching: the field is disabled and cannot hold focus.
    expect(field()).toBeDisabled();
    // The tag filter is enabled all the while, but is not the field to return to.
    expect(screen.getByRole('searchbox', { name: 'Search tags' })).not.toHaveFocus();

    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(field()).toHaveFocus();
  });

  it('refocuses the field without scrolling it into view', async () => {
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: null, result: null, error: null };
    const { rerender } = render(tree());
    const field = () => screen.getByRole('searchbox', { name: 'What do you want to know?' });
    await userEvent.click(field());
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    const focus = vi.spyOn(HTMLElement.prototype, 'focus');

    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(field()).toHaveFocus();
    focus.mockRestore();
  });

  it('leaves focus where the person put it while the search ran', async () => {
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: null, result: null, error: null };
    const { rerender } = render(tree());
    await userEvent.click(screen.getByRole('searchbox', { name: 'What do you want to know?' }));
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    await userEvent.tab();
    expect(screen.getByRole('button', { name: 'Account' })).toHaveFocus();

    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(screen.getByRole('button', { name: 'Account' })).toHaveFocus();
  });

  it('does not take focus when the search was started from outside the field', async () => {
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: null, result: null, error: null };
    const { rerender } = render(tree());
    await userEvent.click(screen.getByRole('button', { name: 'pill' }));
    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree());

    expect(screen.getByRole('searchbox', { name: 'What do you want to know?' })).not.toHaveFocus();
  });
});
