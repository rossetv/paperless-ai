import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';
import { FilterControls } from '../../../components/patterns/FilterControls/FilterControls';
import { SearchTracePanel } from '../SearchTracePanel/SearchTracePanel';
import type { FilterRequest, PhaseRecord } from '../../../api/types';

export interface SearchErrorScreenProps {
  /** The query that failed — recapped in the editable inline field. */
  query: string;
  /** The error detail message to show beneath the headline. */
  message: string;
  /** The active filters — rendered in the left rail so the failure screen keeps
   *  the same chrome as the no-match and results screens. */
  filters: FilterRequest;
  /** Called when the user changes a filter in the rail. */
  onFiltersChange: (filters: FilterRequest) => void;
  /** Called when the user asks to retry — the page re-runs the search. */
  onRetry: () => void;
  /**
   * Called with a new query when the user submits the recap search field —
   * the parent re-runs the search, so the user is not stranded on the error.
   */
  onSearch: (query: string) => void;
  /**
   * The phases that completed before the stream failed. When non-empty the
   * partial trace is folded below the error so the user can see how far the
   * pipeline got. Defaults to empty (no trace shown).
   */
  phaseRecords?: PhaseRecord[];
}

/**
 * The search-failure screen.
 *
 * Shown when a search fails for a reason other than a 503 index-not-ready or
 * a 401 — a 500, a network drop, a malformed response. The same rail chrome as
 * the no-match and results screens (the filter rail on the left, the editable
 * query recap on top) wraps a centred `EmptyState` that reports the failure and
 * offers a "Try again" action; submitting the recap field starts a fresh
 * search, so the user is never stranded. When the stream failed mid-pipeline,
 * a partial `SearchTracePanel` below shows how far it got. Distinct from
 * `NoResultsScreen`, which is a *successful* search that matched nothing.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, EmptyState, Button,
 * FilterControls, SearchTracePanel. No own CSS module (§12.5 — features layer
 * is composition-only).
 */
export function SearchErrorScreen({
  query,
  message,
  filters,
  onFiltersChange,
  onRetry,
  onSearch,
  phaseRecords = [],
}: SearchErrorScreenProps): React.ReactElement {
  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10} align="center">
        {/* Editable query recap — submitting it runs a fresh search. Keyed
            by `query` so it re-seeds whenever a new search is attempted. */}
        <SearchField
          key={query}
          id="search-error-search"
          defaultValue={query}
          onSubmit={onSearch}
        />
        <div role="alert">
          <EmptyState
            icon="warning"
            message="Search failed."
            description={message}
            action={
              <Button variant="primary" onClick={onRetry}>
                Try again
              </Button>
            }
          />
        </div>
        {/* Partial trace — what ran before the failure. Renders nothing when
            no phases completed (the panel returns null on empty input). */}
        <SearchTracePanel phases={phaseRecords} />
      </Stack>
    </SearchScreenLayout>
  );
}
