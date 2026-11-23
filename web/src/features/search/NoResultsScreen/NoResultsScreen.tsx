import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { Text } from '../../../components/primitives/Text/Text';
import { Card } from '../../../components/primitives/Card/Card';
import { FilterControls } from '../../../components/patterns/FilterControls/FilterControls';
import type { FilterPanelState } from '../../../components/patterns/FilterControls/FilterControls';
import { ActiveFiltersStrip } from '../ActiveFiltersStrip/ActiveFiltersStrip';
import { SearchTracePanel } from '../SearchTracePanel/SearchTracePanel';
import { hasActiveFilters } from '../filters';
import { QUICK_FILTERS } from '../lib/quickFilters';
import type { FilterRequest, SearchResponse } from '../../../api/types';
import styles from './NoResultsScreen.module.css';

export interface NoResultsScreenProps {
  result: SearchResponse;
  /** Passed separately because `SearchResponse` does not carry the query. */
  query: string;
  filters: FilterRequest;
  onFiltersChange: (filters: FilterRequest) => void;
  /** The filter panel's open state, held by the page across screens. */
  filterPanel?: FilterPanelState;
  onSearch: (query: string) => void;
  onClearFilters: () => void;
  onSearchWithoutFilters: () => void;
  /** Opens a document from a judge verdict in the trace panel. */
  onPreview: (documentId: number) => void;
}

type CopyConfig = {
  message: string;
  description?: string;
  showFilterActions: boolean;
};

/**
 * The zero-result screen for `no_match` and `clarify` outcomes. The message
 * explains why nothing came back (from `outcome_kind` and `no_match_reason`),
 * and the trace stays inspectable even though no answer was produced.
 */
export function NoResultsScreen({
  result,
  query,
  filters,
  onFiltersChange,
  filterPanel,
  onSearch,
  onClearFilters,
  onSearchWithoutFilters,
  onPreview,
}: NoResultsScreenProps): React.ReactElement {
  const { outcome_kind, no_match_reason, candidate_count, answer, trace, cost } = result;
  const filtersActive = hasActiveFilters(filters);

  function buildCopy(): CopyConfig {
    if (outcome_kind === 'clarify') {
      return {
        message: answer,
        description: 'Add a document type, date range, or correspondent to narrow things down.',
        showFilterActions: false,
      };
    }

    // outcome_kind === 'no_match'
    switch (no_match_reason) {
      case 'judge_rejected': {
        const countText =
          candidate_count != null ? String(candidate_count) : 'some';
        return {
          message: `I found ${countText} document${candidate_count === 1 ? '' : 's'}, but none matched your question. Try rephrasing.`,
          showFilterActions: filtersActive,
        };
      }

      case 'weak_relevance': {
        return {
          message: "The closest matches weren't relevant enough to answer. Try rephrasing.",
          showFilterActions: filtersActive,
        };
      }

      case 'empty_retrieval':
      default: {
        if (filtersActive) {
          return {
            message: 'Your filters narrowed the search to zero results.',
            description: 'Try removing the document-type or tag filters, or rephrase the question.',
            showFilterActions: true,
          };
        }
        return {
          message: 'Nothing in your library matched that search.',
          showFilterActions: false,
        };
      }
    }
  }

  const { message, description, showFilterActions } = buildCopy();

  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls
          filters={filters}
          onFiltersChange={onFiltersChange}
          {...filterPanel}
        />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Editable query recap */}
        <SearchField
          key={query}
          ariaLabel="What do you want to know?"
          id="no-results-search"
          defaultValue={query}
          onSubmit={onSearch}
        />

        {/* Active filters (0 documents) */}
        <ActiveFiltersStrip
          filters={filters}
          docCount={0}
          onClearAll={onClearFilters}
        />

        <EmptyState
          icon="search"
          message={message}
          {...(description !== undefined ? { description } : {})}
          {...(showFilterActions
            ? {
                action: (
                  <Stack direction="horizontal" gap={6}>
                    <Button variant="secondary" onClick={onClearFilters}>
                      Clear filters
                    </Button>
                    <Button variant="primary" onClick={onSearchWithoutFilters}>
                      Search without filters
                    </Button>
                  </Stack>
                ),
              }
            : {})}
        />

        {/* Empty when a clarify short-circuits before retrieval. */}
        <SearchTracePanel
          phases={trace.phases}
          cost={cost}
          onPreview={onPreview}
        />

        {/* "Try instead" suggestions */}
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
