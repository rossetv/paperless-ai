import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';
import { FilterControls } from '../FilterControls/FilterControls';
import type { FilterRequest } from '../../../api/types';

export interface NoResultsScreenProps {
  /** The query that produced no results — recapped in the inline field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
  /** Called when the user asks to clear all filters. */
  onClearFilters: () => void;
  /** Called when the user asks to re-run the search with no filters. */
  onSearchWithoutFilters: () => void;
}

/**
 * The search no-results screen.
 *
 * The rail+content layout: the filter rail, a query recap, and an
 * `EmptyState` explaining that no documents matched, with two recovery
 * actions — clear the filters, or re-run the search without any filters.
 * Both actions are delegated to the parent.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, EmptyState, Button,
 * FilterControls. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function NoResultsScreen({
  query,
  filters,
  onFiltersChange,
  onClearFilters,
  onSearchWithoutFilters,
}: NoResultsScreenProps): React.ReactElement {
  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        <SearchField
          id="no-results-search"
          value={query}
          disabled
          onSubmit={() => {}}
        />

        <EmptyState
          icon="search"
          message="No documents matched."
          description="Your filters narrowed the search to zero results. Try removing the document-type or tag filters, or rephrase the question."
          action={
            <Stack direction="horizontal" gap={6}>
              <Button variant="secondary" onClick={onClearFilters}>
                Clear filters
              </Button>
              <Button variant="primary" onClick={onSearchWithoutFilters}>
                Search without filters
              </Button>
            </Stack>
          }
        />
      </Stack>
    </SearchScreenLayout>
  );
}
