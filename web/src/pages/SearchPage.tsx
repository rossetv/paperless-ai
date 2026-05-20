/**
 * Search page — the primary view of the application.
 *
 * Composes:
 *   - `NavBar`        — application chrome
 *   - `Page` + `Container` — layout shell
 *   - `SearchBar`     — query input (feature)
 *   - `FilterControls`— facet filters (feature, driven by useFacets)
 *   - `AnswerCard`    — synthesised answer with citation buttons (feature)
 *   - `SourceList`    — ranked source documents with highlight support (feature)
 *   - `QueryPlanSummary` — search transparency line (feature)
 *
 * States handled:
 *   - Idle            — no query submitted yet; blank results area
 *   - Loading         — query submitted, response pending; Spinner shown
 *   - Success         — `AnswerCard` + `SourceList` + `QueryPlanSummary`
 *   - Empty           — search returned no sources; `EmptyState` shown
 *   - Initialising    — server replied 503 with "index-not-ready"; dedicated message
 *   - Unauthenticated — any 401 from the API; `logout()` called → routes to LoginPage
 *
 * Zero styling of its own (CODE_GUIDELINES §12.5): no `.module.css`, no
 * hardcoded design values.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { Container } from '../components/layout/Container/Container';
import { NavBar } from '../components/layout/NavBar/NavBar';
import { Stack } from '../components/layout/Stack/Stack';
import { Spinner } from '../components/primitives/Spinner/Spinner';
import { EmptyState } from '../components/patterns/EmptyState/EmptyState';
import { SearchBar } from '../features/search/SearchBar/SearchBar';
import { FilterControls } from '../features/search/FilterControls/FilterControls';
import { AnswerCard } from '../features/search/AnswerCard/AnswerCard';
import { SourceList } from '../features/search/SourceList/SourceList';
import { QueryPlanSummary } from '../features/search/QueryPlanSummary/QueryPlanSummary';
import { useSearch } from '../api/hooks';
import { Unauthenticated, ApiError } from '../api/client';
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
 * Returns true when the error indicates the search index has not yet finished
 * building — the server sends a 503 with the detail "index-not-ready".
 */
function isIndexNotReady(error: Error): boolean {
  return error instanceof ApiError && error.status === 503;
}

/**
 * The main search page.
 *
 * Holds the current query and filter state locally. Drives `useSearch` with
 * those values; the hook is disabled while the query is empty so no spurious
 * request fires on initial render. Citation activation updates `highlightedIndex`
 * which is passed down to `SourceList` to scroll/highlight the matching card.
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

  // ------------------------------------------------------------------
  // Results area — one of: idle / loading / initialising / empty / results
  // ------------------------------------------------------------------

  function renderResults(): React.ReactNode {
    // Idle: no query submitted yet
    if (query.trim().length === 0) {
      return null;
    }

    // Loading: request in flight
    if (searchResult.isPending || searchResult.isFetching) {
      return <Spinner label="Searching…" size="large" />;
    }

    // Error: distinguish 503 index-not-ready from other failures
    if (searchResult.isError && searchResult.error !== null) {
      if (isIndexNotReady(searchResult.error)) {
        return (
          <EmptyState
            icon="info"
            message="The index is initialising"
            description="The search index is still being built. Try again in a moment."
          />
        );
      }
      // Other errors (non-401: 401 is handled via logout effect above)
      if (!(searchResult.error instanceof Unauthenticated)) {
        return (
          <EmptyState
            icon="warning"
            message="Search failed"
            description={searchResult.error.message}
          />
        );
      }
      return null;
    }

    // Success
    if (searchResult.isSuccess && searchResult.data !== undefined) {
      const { answer, sources, plan, stats } = searchResult.data;

      // Empty result: the pipeline returned nothing
      if (sources.length === 0) {
        return (
          <EmptyState
            icon="search"
            message="No results found"
            description="Try adjusting your query or removing some filters."
          />
        );
      }

      return (
        <Stack direction="vertical" gap={8}>
          <AnswerCard
            answer={answer}
            sources={sources}
            onCitationActivate={handleCitationActivate}
          />
          <SourceList
            sources={sources}
            {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
          />
          <QueryPlanSummary plan={plan} stats={stats} />
        </Stack>
      );
    }

    return null;
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
          {renderResults()}
        </Stack>
      </Container>
    </Page>
  );
}
