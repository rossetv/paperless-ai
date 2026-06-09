/**
 * Search page — the primary view of the application.
 *
 * A pure orchestrator. It owns the query, filter and citation-highlight state
 * (query and filters via `useSearchUrlState`; highlight index stays local as
 * ephemeral interaction state), drives the LIVE streaming search
 * (`useStreamingSearch`), and selects which search screen to render:
 *
 *   - no query                       → IdleScreen (the hero)
 *   - search streaming               → LoadingScreen (live per-phase rail)
 *   - search error, 503              → IndexNotReadyScreen
 *   - search error, 401              → invalidate `me`; ProtectedRoute → login
 *   - search error, other            → SearchErrorScreen (+ partial trace)
 *   - done, zero sources             → NoResultsScreen
 *   - done, sources                  → ResultsScreen (+ SearchTracePanel)
 *
 * The search runs over `POST /api/search/stream` (NDJSON): the planner rewrite,
 * vector-gate drops, per-document judge verdicts, synthesis and refinement are
 * streamed live into the loading rail, and fold into the "How this answer was
 * found" trace panel — with per-step and total token/dollar cost — once the
 * answer lands. A `run(query, filters)` is fired by an effect whenever the URL's
 * query/filters change, mirroring the old query-key-driven refetch.
 *
 * Opening a document preview navigates to `/document/<id>?<searchString>` so
 * the preview URL is shareable and the back button returns to the results.
 *
 * The page composes the Wave 1 `AppNavBar` shell and the `features/search`
 * screen components; it reaches no primitive or pattern directly (§12.3) and
 * ships no styling of its own (§12.5).
 *
 * Auth: a 401 from the stream's initial response means the session cookie has
 * expired; the page invalidates the cached `me` query so `useAuth` re-resolves
 * and `ProtectedRoute` redirects the user to the login screen. (Preserved
 * exactly from the pre-streaming behaviour — `useStreamingSearch` surfaces the
 * HTTP status of a failed initial response on `state.error.status`.)
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IdleScreen } from '../features/search/IdleScreen/IdleScreen';
import { LoadingScreen } from '../features/search/LoadingScreen/LoadingScreen';
import { ResultsScreen } from '../features/search/ResultsScreen/ResultsScreen';
import { NoResultsScreen } from '../features/search/NoResultsScreen/NoResultsScreen';
import { IndexNotReadyScreen } from '../features/search/IndexNotReadyScreen/IndexNotReadyScreen';
import { SearchErrorScreen } from '../features/search/SearchErrorScreen/SearchErrorScreen';
import { useStreamingSearch } from '../features/search/useStreamingSearch';
import { ME_QUERY_KEY } from '../api/hooks';
import {
  useSearchUrlState,
  EMPTY_FILTERS,
} from '../features/search/useSearchUrlState';

/**
 * The main search page — orchestrates the search screens over a live stream.
 */
export function SearchPage(): React.ReactElement {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { query, filters, setQuery, setFilters, searchString } =
    useSearchUrlState();
  const [highlightedIndex, setHighlightedIndex] = React.useState<
    number | undefined
  >(undefined);

  const { state, run } = useStreamingSearch();

  // Kick off (or re-run) the stream whenever the URL's query/filters change to
  // a non-empty query — the streaming equivalent of the old query-key refetch.
  // `run` is referentially stable (useCallback []), so the effect fires only on
  // a genuine query/filter change. Filters are serialised so a fresh-but-equal
  // object identity does not retrigger a search.
  const filtersKey = JSON.stringify(filters);
  React.useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length > 0) {
      run(trimmed, filters);
    }
    // filters is reconstructed from filtersKey; depending on the key keeps the
    // effect stable while still reacting to a real filter change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, filtersKey, run]);

  // A 401 from the stream's initial response means the session expired.
  // Invalidate the `me` query so `useAuth` re-resolves and ProtectedRoute
  // redirects. Preserves the pre-streaming auth behaviour exactly. Guarded on
  // the error belonging to the current query so a stale 401 cannot fire.
  React.useEffect(() => {
    if (
      query.trim().length > 0 &&
      state.query === query.trim() &&
      state.status === 'error' &&
      state.error?.status === 401
    ) {
      void queryClient.invalidateQueries({ queryKey: ME_QUERY_KEY });
    }
  }, [query, state.query, state.status, state.error, queryClient]);

  function runSearch(submitted: string): void {
    setQuery(submitted.trim());
    setHighlightedIndex(undefined);
  }

  function clearFilters(): void {
    setFilters(EMPTY_FILTERS);
  }

  function handleCitationActivate(index: number): void {
    setHighlightedIndex(index);
  }

  // useCallback so the reference is stable across renders — SourceCard is
  // React.memo'd and receives this as onPreview, so an inline/unstable handler
  // would defeat the memo and re-render every source card on each parent render.
  const openPreview = React.useCallback(
    (documentId: number): void => {
      navigate(`/document/${documentId}${searchString}`);
    },
    [navigate, searchString],
  );

  /** Pick the screen to render from the query and the stream state. */
  function renderScreen(): React.ReactElement {
    // Idle — no query submitted.
    if (query.trim().length === 0) {
      return <IdleScreen onSearch={runSearch} />;
    }

    // A terminal state (done/error) is authoritative only when it belongs to
    // the CURRENT query. Between the URL changing to a new query and the
    // trigger effect firing `run`, the state still holds the previous query's
    // result — showing it would flash a stale answer. Until the new stream's
    // `start` lands, treat such a state as still loading.
    const stateIsCurrent = state.query === query.trim();

    // Error states — mapped from the initial-response HTTP status.
    if (stateIsCurrent && state.status === 'error' && state.error !== null) {
      if (state.error.status === 503) {
        return <IndexNotReadyScreen onRetry={() => run(query.trim(), filters)} />;
      }
      if (state.error.status === 401) {
        // The effect above invalidates `me`; ProtectedRoute will redirect.
        // Render the idle hero as a calm placeholder until it does.
        return <IdleScreen onSearch={runSearch} />;
      }
      return (
        <SearchErrorScreen
          query={query}
          message={state.error.message}
          phaseRecords={state.phaseRecords}
          onRetry={() => run(query.trim(), filters)}
          onSearch={runSearch}
        />
      );
    }

    // Done — render results (or a no-results nudge), plus the trace panel.
    if (stateIsCurrent && state.status === 'done' && state.result !== null) {
      const result = state.result;
      if (result.sources.length === 0) {
        return (
          <NoResultsScreen
            query={query}
            filters={filters}
            onFiltersChange={setFilters}
            onSearch={runSearch}
            onClearFilters={clearFilters}
            onSearchWithoutFilters={clearFilters}
          />
        );
      }
      return (
        <ResultsScreen
          query={query}
          filters={filters}
          result={result}
          docCount={result.sources.length}
          onFiltersChange={setFilters}
          onSearch={runSearch}
          onClearFilters={clearFilters}
          onCitationActivate={handleCitationActivate}
          onPreview={openPreview}
          {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
        />
      );
    }

    // Otherwise the stream is starting or in flight — the live loading rail.
    // (Default before the first effect runs and while status is 'streaming'.)
    return (
      <LoadingScreen
        query={query}
        filters={filters}
        onFiltersChange={setFilters}
        phaseRecords={state.phaseRecords}
        activePhase={state.activePhase}
      />
    );
  }

  return (
    <Page>
      <AppNavBar />
      {renderScreen()}
    </Page>
  );
}
