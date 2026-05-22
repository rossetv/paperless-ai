/**
 * Search page — the primary view of the application.
 *
 * A pure orchestrator. It owns the query, filter, citation-highlight and
 * open-preview state, drives `useSearch`, and selects which search screen to
 * render:
 *
 *   - no query                       → IdleScreen (the hero)
 *   - a document preview is open      → DocumentPreviewScreen (overlay)
 *   - search in flight               → LoadingScreen
 *   - search error, 503              → IndexNotReadyScreen
 *   - search error, 401              → invalidate `me`; ProtectedRoute → login
 *   - search error, other            → SearchErrorScreen
 *   - success, zero sources          → NoResultsScreen
 *   - success, sources               → ResultsScreen
 *
 * The page composes the Wave 1 `AppNavBar` shell and the `features/search`
 * screen components; it reaches no primitive or pattern directly (§12.3) and
 * ships no styling of its own (§12.5).
 *
 * Auth: a 401 from an in-flight search means the session cookie has expired;
 * the page invalidates the cached `me` query so `useAuth` re-resolves and
 * `ProtectedRoute` redirects the user to the login screen.
 */

import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IdleScreen } from '../features/search/IdleScreen/IdleScreen';
import { LoadingScreen } from '../features/search/LoadingScreen/LoadingScreen';
import { ResultsScreen } from '../features/search/ResultsScreen/ResultsScreen';
import { NoResultsScreen } from '../features/search/NoResultsScreen/NoResultsScreen';
import { IndexNotReadyScreen } from '../features/search/IndexNotReadyScreen/IndexNotReadyScreen';
import { SearchErrorScreen } from '../features/search/SearchErrorScreen/SearchErrorScreen';
import { DocumentPreviewScreen } from '../features/search/DocumentPreviewScreen/DocumentPreviewScreen';
import { useSearch, ME_QUERY_KEY } from '../api/hooks';
import { ApiError, Unauthenticated } from '../api/client';
import type { FilterRequest } from '../api/types';

/** The empty filter state — every filter cleared. */
const EMPTY_FILTERS: FilterRequest = {
  tag_ids: [],
  correspondent_id: null,
  document_type_id: null,
  date_from: null,
  date_to: null,
};

/** True when the error is the server's 503 "index not ready" signal. */
function isIndexNotReady(error: Error): boolean {
  return error instanceof ApiError && error.status === 503;
}

/**
 * The main search page — orchestrates the search screens.
 */
export function SearchPage(): React.ReactElement {
  const queryClient = useQueryClient();

  const [query, setQuery] = React.useState('');
  const [filters, setFilters] = React.useState<FilterRequest>(EMPTY_FILTERS);
  const [highlightedIndex, setHighlightedIndex] = React.useState<
    number | undefined
  >(undefined);
  const [previewDocumentId, setPreviewDocumentId] = React.useState<
    number | null
  >(null);

  const searchResult = useSearch({ query, filters });

  // A 401 from a real in-flight search means the session expired. Invalidate
  // the `me` query so `useAuth` re-resolves and ProtectedRoute redirects.
  React.useEffect(() => {
    if (
      query.trim().length > 0 &&
      searchResult.isError &&
      searchResult.error instanceof Unauthenticated
    ) {
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    }
  }, [query, searchResult.isError, searchResult.error, queryClient]);

  function runSearch(submitted: string): void {
    setQuery(submitted.trim());
    setHighlightedIndex(undefined);
    setPreviewDocumentId(null);
  }

  function handleFiltersChange(updated: FilterRequest): void {
    setFilters(updated);
  }

  function clearFilters(): void {
    setFilters(EMPTY_FILTERS);
  }

  function handleCitationActivate(index: number): void {
    setHighlightedIndex(index);
  }

  function openPreview(documentId: number): void {
    setPreviewDocumentId(documentId);
  }

  function closePreview(): void {
    setPreviewDocumentId(null);
  }

  /** Pick the screen to render from the query and the search result. */
  function renderScreen(): React.ReactElement {
    // Idle — no query submitted.
    if (query.trim().length === 0) {
      return <IdleScreen onSearch={runSearch} />;
    }

    // A document preview overlays everything else.
    if (
      previewDocumentId !== null &&
      searchResult.isSuccess &&
      searchResult.data !== undefined
    ) {
      const source = searchResult.data.sources.find(
        (s) => s.document_id === previewDocumentId,
      );
      if (source !== undefined) {
        return (
          <DocumentPreviewScreen source={source} onClose={closePreview} />
        );
      }
    }

    // In flight.
    if (searchResult.isPending || searchResult.isFetching) {
      return (
        <LoadingScreen
          query={query}
          filters={filters}
          onFiltersChange={handleFiltersChange}
        />
      );
    }

    // Error states.
    if (searchResult.isError && searchResult.error !== null) {
      if (isIndexNotReady(searchResult.error)) {
        return <IndexNotReadyScreen onRetry={() => searchResult.refetch()} />;
      }
      if (searchResult.error instanceof Unauthenticated) {
        // The effect above invalidates `me`; ProtectedRoute will redirect.
        // Render the idle hero as a calm placeholder until it does.
        return <IdleScreen onSearch={runSearch} />;
      }
      return (
        <SearchErrorScreen
          message={searchResult.error.message}
          onRetry={() => searchResult.refetch()}
        />
      );
    }

    // Success.
    if (searchResult.isSuccess && searchResult.data !== undefined) {
      if (searchResult.data.sources.length === 0) {
        return (
          <NoResultsScreen
            query={query}
            filters={filters}
            onFiltersChange={handleFiltersChange}
            onClearFilters={clearFilters}
            onSearchWithoutFilters={() => {
              clearFilters();
            }}
          />
        );
      }
      return (
        <ResultsScreen
          query={query}
          filters={filters}
          result={searchResult.data}
          onFiltersChange={handleFiltersChange}
          onCitationActivate={handleCitationActivate}
          onPreview={openPreview}
          {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
        />
      );
    }

    // Unreachable in practice — a calm fallback.
    return <IdleScreen onSearch={runSearch} />;
  }

  return (
    <Page>
      <AppNavBar />
      {renderScreen()}
    </Page>
  );
}
