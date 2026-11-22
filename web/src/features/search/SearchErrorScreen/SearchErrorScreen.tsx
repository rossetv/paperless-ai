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
  /** The failed query, recapped in the editable search field. */
  query: string;
  message: string;
  /** Shown in the rail so this screen keeps the results screens' chrome. */
  filters: FilterRequest;
  onFiltersChange: (filters: FilterRequest) => void;
  onRetry: () => void;
  /** Called when the recap field is submitted, so the user is not stranded. */
  onSearch: (query: string) => void;
  /** Phases that completed before the failure, shown as a partial trace. */
  phaseRecords?: PhaseRecord[];
}

/**
 * Shown when a search fails for any reason other than 503 (index not ready) or
 * 401: a 500, a network drop, a malformed response. Unlike `NoResultsScreen`,
 * which is a successful search that matched nothing.
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
        {/* Keyed by `query` so it re-seeds whenever a new search is attempted. */}
        <SearchField
          key={query}
          ariaLabel="What do you want to know?"
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
        {/* Partial trace of what ran before the failure */}
        <SearchTracePanel phases={phaseRecords} />
      </Stack>
    </SearchScreenLayout>
  );
}
