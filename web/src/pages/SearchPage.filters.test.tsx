import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { SearchResponse } from '../api/types';
import { SearchPage } from './SearchPage';

vi.mock('../features/shell/AppNavBar/AppNavBar', () => ({
  AppNavBar: () => <div />,
}));

// The real screens and filter panel render; only the data behind them is faked.
vi.mock('../api/hooks', () => ({
  ME_QUERY_KEY: ['auth', 'me'],
  useFacets: () => ({
    isLoading: false,
    isError: false,
    data: {
      correspondents: [{ kind: 'correspondent', id: 1, name: 'Npower' }],
      document_types: [],
      tags: [],
      date_range: { min: null, max: null },
    },
  }),
}));

let streamState: Record<string, unknown> = {};
vi.mock('../features/search/useStreamingSearch', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../features/search/useStreamingSearch')>()),
  useStreamingSearch: () => ({ state: streamState, run: vi.fn() }),
}));

const RESULT = {
  outcome_kind: 'answered',
  answer: 'You paid Npower.',
  sources: [],
  plan: { specs: [] },
  stats: { llm_calls: 1, latency_ms: 10, refined: false },
  trace: { phases: [] },
  cost: { tokens: { prompt: 1, completion: 1, reasoning: 0, total: 2 }, usd: 0, local: true },
} as unknown as SearchResponse;

function tree(url: string) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[url]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const filtersToggle = () => screen.getByRole('button', { name: /filters/i });

function narrowScreen(narrow: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: narrow && query === '(max-width: 834px)',
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('SearchPage filter panel', () => {
  it('keeps the panel open on a narrow screen when a filter change restarts the search', async () => {
    narrowScreen(true);
    streamState = { status: 'done', query: 'bills', phaseRecords: [], activePhase: null, result: RESULT, error: null };
    const { rerender } = render(tree('/?q=bills'));
    expect(filtersToggle()).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(filtersToggle());
    await userEvent.click(screen.getByRole('combobox', { name: /correspondent/i }));
    await userEvent.click(screen.getByRole('option', { name: 'Npower' }));

    // The new filters restart the search: the loading screen mounts its own panel.
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: 'plan', result: null, error: null };
    rerender(tree('/?q=bills&correspondent_id=1'));
    expect(filtersToggle()).toHaveAttribute('aria-expanded', 'true');

    // And the answer arriving mounts the results screen's.
    streamState = { ...streamState, status: 'done', result: RESULT };
    rerender(tree('/?q=bills&correspondent_id=1'));
    expect(filtersToggle()).toHaveAttribute('aria-expanded', 'true');
  });

  it('keeps the panel closed across screens when the person closed it', async () => {
    narrowScreen(false);
    streamState = { status: 'done', query: 'bills', phaseRecords: [], activePhase: null, result: RESULT, error: null };
    const { rerender } = render(tree('/?q=bills'));
    expect(filtersToggle()).toHaveAttribute('aria-expanded', 'true');

    await userEvent.click(filtersToggle());
    streamState = { status: 'streaming', query: 'bills', phaseRecords: [], activePhase: 'plan', result: null, error: null };
    rerender(tree('/?q=bills&correspondent_id=1'));

    expect(filtersToggle()).toHaveAttribute('aria-expanded', 'false');
  });
});
