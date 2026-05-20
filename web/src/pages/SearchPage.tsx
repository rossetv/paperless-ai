/**
 * Search page — the primary view of the application.
 *
 * Composes:
 *   - `NavBar`         — application chrome
 *   - `Page` + `Container` — layout shell
 *   - `SearchBar`      — query input (feature)
 *   - `FilterControls` — facet filters (feature, driven by useFacets)
 *   - `SearchResults`  — the result-state area: loading / empty / error /
 *                        answer + sources + plan (feature)
 *
 * The page owns only the query and filter state and the auth-routing effect.
 * Every result-state presentation lives in `SearchResults`; the page never
 * reaches a primitive or a pattern directly (§12.3) and ships no styling of its
 * own (§12.5) — no `.module.css`, no hardcoded design values.
 *
 * Auth: an `Unauthenticated` error from an in-flight search means the session
 * cookie has expired; the page flips auth state so the router sends the user to
 * the login screen.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { Container } from '../components/layout/Container/Container';
import { NavBar } from '../components/layout/NavBar/NavBar';
import { Stack } from '../components/layout/Stack/Stack';
import { SearchBar } from '../features/search/SearchBar/SearchBar';
import { FilterControls } from '../features/search/FilterControls/FilterControls';
import { SearchResults } from '../features/search/SearchResults/SearchResults';
import { useSearch } from '../api/hooks';
import { Unauthenticated } from '../api/client';
import type { FilterRequest } from '../api/types';
import { useAuth } from '../hooks/useAuth';

const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

/**
 * The main search page.
 *
 * Holds the current query and filter state locally. Drives `useSearch` with
 * those values; the hook is disabled while the query is empty so no spurious
 * request fires on initial render. Citation activation updates `highlightedIndex`
 * which is passed down to `SearchResults` to scroll/highlight the matching card.
 */
export function SearchPage(): React.ReactElement {
  const { logout } = useAuth();

  const [query, setQuery] = React.useState('');
  const [filters, setFilters] = React.useState<FilterRequest>(EMPTY_FILTERS);
  const [highlightedIndex, setHighlightedIndex] = React.useState<
    number | undefined
  >(undefined);

  const searchResult = useSearch({ query, filters });

  // An Unauthenticated error from a real in-flight search means the session
  // cookie has expired or was never set. Only act when there is an active query
  // — the hook is disabled (and may report a stale error) when the query is
  // empty. Flip auth state → the router sends us to LoginPage.
  React.useEffect(() => {
    if (
      query.trim().length > 0 &&
      searchResult.isError &&
      searchResult.error instanceof Unauthenticated
    ) {
      logout();
    }
  }, [query, searchResult.isError, searchResult.error, logout]);

  function handleSearch(submittedQuery: string): void {
    setQuery(submittedQuery);
    setHighlightedIndex(undefined);
  }

  function handleFiltersChange(updated: FilterRequest): void {
    setFilters(updated);
  }

  function handleCitationActivate(index: number): void {
    setHighlightedIndex(index);
  }

  return (
    <Page>
      <NavBar brand="Paperless AI Search" />
      <Container>
        <Stack direction="vertical" gap={8}>
          <SearchBar onSearch={handleSearch} disabled={searchResult.isFetching} />
          <FilterControls
            filters={filters}
            onFiltersChange={handleFiltersChange}
          />
          <SearchResults
            query={query}
            result={searchResult}
            onCitationActivate={handleCitationActivate}
            {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
          />
        </Stack>
      </Container>
    </Page>
  );
}
