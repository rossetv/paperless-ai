/**
 * Search page — orchestrates the search screens over the live NDJSON stream
 * (`useStreamingSearch`). Query and filters live in the URL; the highlighted
 * citation stays local.
 *
 *   - no query                           → IdleScreen
 *   - streaming                          → LoadingScreen (live per-phase rail)
 *   - error, 503                         → IndexNotReadyScreen
 *   - error, 401                         → invalidate `me`; ProtectedRoute → login
 *   - error, other                       → SearchErrorScreen (+ partial trace)
 *   - done, outcome `clarify`/`no_match` → NoResultsScreen (+ trace)
 *   - done, outcome `answered`           → ResultsScreen (+ SearchTracePanel)
 *
 * Opening a preview navigates to `/document/<id>?<searchString>` so the URL is
 * shareable and the back button returns to the results.
 */

import React from 'react';
import { useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IdleScreen } from '../features/search/IdleScreen/IdleScreen';
import { LoadingScreen } from '../features/search/LoadingScreen/LoadingScreen';
import { ResultsScreen } from '../features/search/ResultsScreen/ResultsScreen';
import { NoResultsScreen } from '../features/search/NoResultsScreen/NoResultsScreen';
import { IndexNotReadyScreen } from '../features/search/IndexNotReadyScreen/IndexNotReadyScreen';
import { SearchErrorScreen } from '../features/search/SearchErrorScreen/SearchErrorScreen';
import {
  RETURN_TO_RESULTS,
  useStreamingSearch,
} from '../features/search/useStreamingSearch';
import { ME_QUERY_KEY } from '../api/hooks';
import {
  useSearchUrlState,
  EMPTY_FILTERS,
} from '../features/search/useSearchUrlState';

/** The ids of the one main search field each screen renders. */
const MAIN_FIELD_SELECTOR =
  '#idle-search, #loading-search, #results-search, #no-results-search, #search-error-search';

export function SearchPage(): React.ReactElement {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const { query, filters, setQuery, setFilters, searchString } =
    useSearchUrlState();
  const [highlightedIndex, setHighlightedIndex] = React.useState<
    number | undefined
  >(undefined);

  // Only Back/Forward, or the document page's link back to the results, shows
  // the kept answer; any other link or a new query searches.
  const location = useLocation();
  const returning =
    (location.state as Partial<typeof RETURN_TO_RESULTS> | null)?.returnToResults === true;
  const { state, run } = useStreamingSearch(
    useNavigationType() === 'POP' || returning,
  );

  // Re-run the stream whenever the URL's query/filters change to a non-empty
  // query. Filters are serialised so a fresh-but-equal object does not
  // retrigger a search; `run` is referentially stable.
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

  // A 401 from the stream's initial response means the session expired:
  // invalidate `me` so `useAuth` re-resolves and ProtectedRoute redirects.
  // Guarded on the error belonging to the current query so a stale 401 cannot fire.
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

  // Each screen has its own search field, so a submit unmounts the one the
  // person typed in; focus goes back to the new screen's own field, never to
  // another search input such as the filter panel's tag search.
  const refocusField = React.useRef(false);

  function runSearch(submitted: string): void {
    const active = document.activeElement;
    refocusField.current =
      active instanceof HTMLElement &&
      (active.matches('input[type="search"]') || active.getAttribute('aria-label') === 'Search');
    setQuery(submitted.trim());
    setHighlightedIndex(undefined);
  }

  // The person moving focus themselves while the search runs cancels the return.
  React.useEffect(() => {
    function onFocusIn(event: FocusEvent): void {
      if (!(event.target instanceof Element) || !event.target.matches(MAIN_FIELD_SELECTOR)) {
        refocusField.current = false;
      }
    }
    document.addEventListener('focusin', onFocusIn);
    return () => document.removeEventListener('focusin', onFocusIn);
  }, []);

  const settled =
    state.query === query.trim() && (state.status === 'done' || state.status === 'error');
  React.useEffect(() => {
    if (!refocusField.current) {
      return;
    }
    const field = document.querySelector<HTMLInputElement>(`:is(${MAIN_FIELD_SELECTOR}):not(:disabled)`);
    if (field !== null) {
      // The page is already where the answer is; a short viewport must not jump to the field.
      field.focus({ preventScroll: true });
      field.setSelectionRange(field.value.length, field.value.length);
    }
    // A field that is not there yet (the loading screen's is disabled) keeps the
    // request pending until the search settles.
    if (field !== null || settled) {
      refocusField.current = false;
    }
  });

  function clearFilters(): void {
    setFilters(EMPTY_FILTERS);
  }

  function handleCitationActivate(index: number): void {
    setHighlightedIndex(index);
  }

  // Stable reference: SourceCard is React.memo'd and receives this as onPreview.
  const openPreview = React.useCallback(
    (documentId: number): void => {
      navigate(`/document/${documentId}${searchString}`);
    },
    [navigate, searchString],
  );

  // The idle hero brings its own h1; every other screen needs the hidden one.
  const showsIdleHero =
    query.trim().length === 0 ||
    (state.query === query.trim() &&
      state.status === 'error' &&
      state.error?.status === 401);

  /** Pick the screen to render from the query and the stream state. */
  function renderScreen(): React.ReactElement {
    if (query.trim().length === 0) {
      return <IdleScreen onSearch={runSearch} />;
    }

    // A terminal state (done/error) is authoritative only when it belongs to
    // the CURRENT query. Between the URL changing to a new query and the
    // trigger effect firing `run`, the state still holds the previous query's
    // result — showing it would flash a stale answer. Until the new stream's
    // `start` lands, treat such a state as still loading.
    const stateIsCurrent = state.query === query.trim();

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
          filters={filters}
          onFiltersChange={setFilters}
          phaseRecords={state.phaseRecords}
          onRetry={() => run(query.trim(), filters)}
          onSearch={runSearch}
        />
      );
    }

    if (stateIsCurrent && state.status === 'done' && state.result !== null) {
      const result = state.result;
      if (result.outcome_kind !== 'answered') {
        return (
          <NoResultsScreen
            result={result}
            query={query}
            filters={filters}
            onFiltersChange={setFilters}
            onSearch={runSearch}
            onClearFilters={clearFilters}
            onSearchWithoutFilters={clearFilters}
            onPreview={openPreview}
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

    // Starting or in flight, including before the first effect runs.
    return (
      <LoadingScreen
        query={query}
        filters={filters}
        onFiltersChange={setFilters}
        phaseRecords={state.phaseRecords}
        activePhase={state.activePhase}
        onPreview={openPreview}
      />
    );
  }

  return (
    <Page>
      <AppNavBar />
      {!showsIdleHero && <h1 className="visually-hidden">Search</h1>}
      {renderScreen()}
    </Page>
  );
}
