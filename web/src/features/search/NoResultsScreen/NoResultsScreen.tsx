import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Text } from '../../../components/primitives/Text/Text';
import { Card } from '../../../components/primitives/Card/Card';
import { FilterControls } from '../FilterControls/FilterControls';
import { ActiveFiltersStrip } from '../ActiveFiltersStrip/ActiveFiltersStrip';
import { QUICK_FILTERS } from '../lib/quickFilters';
import type { FilterRequest } from '../../../api/types';
import styles from './NoResultsScreen.module.css';

export interface NoResultsScreenProps {
  /** The query that produced no results — recapped in the inline field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
  /**
   * Called with a new query when the user submits the recap search field —
   * the parent re-runs the search, so a second search needs no reload.
   */
  onSearch: (query: string) => void;
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
 * Text, Icon, FilterControls, ActiveFiltersStrip. No own CSS module (§12.5 —
 * features layer is composition-only).
 */
export function NoResultsScreen({
  query,
  filters,
  onFiltersChange,
  onSearch,
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
        {/* Query recap — editable: submitting it re-runs the search with the
            new query, so the user is never stranded on this screen. Keyed by
            `query` so it re-seeds whenever a fresh search lands. */}
        <SearchField
          key={query}
          id="no-results-search"
          defaultValue={query}
          onSubmit={onSearch}
        />

        {/* MINOR 1 — active-filters summary row (0 documents). Reuses the
            same ActiveFiltersStrip as ResultsScreen with docCount=0. Renders
            nothing when no filters are set. */}
        <ActiveFiltersStrip
          filters={filters}
          docCount={0}
          onClearAll={onClearFilters}
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

        {/* "Try instead" suggestion block — three canned queries from
            QUICK_FILTERS (shared with IdleScreen). Each row calls onSearch
            so the user navigates directly to a fresh result. Uses Card and
            Button primitives so focus rings and design tokens come for free. */}
        <Card>
          <Stack direction="vertical" gap={6}>
            <Text as="p" variant="caption-bold" tone="secondary">
              Try instead
            </Text>
            {QUICK_FILTERS.slice(0, 3).map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => onSearch(suggestion)}
                className={styles['suggestion-row']}
              >
                <Icon name="search" size="small" />
                <Text as="span" variant="body" tone="primary">
                  {suggestion}
                </Text>
              </button>
            ))}
          </Stack>
        </Card>
      </Stack>
    </SearchScreenLayout>
  );
}
