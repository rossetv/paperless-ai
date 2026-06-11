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
import { SearchTracePanel } from '../SearchTracePanel/SearchTracePanel';
import { hasActiveFilters } from '../filters';
import { QUICK_FILTERS } from '../lib/quickFilters';
import type { FilterRequest, SearchResponse } from '../../../api/types';
import styles from './NoResultsScreen.module.css';

export interface NoResultsScreenProps {
  /** The full search response — used to derive the reason message and trace. */
  result: SearchResponse;
  /**
   * The query string that produced this result — recapped in the inline
   * search field so the user can edit and re-run it. The parent (SearchPage)
   * owns the query via URL state; it is not stored on `SearchResponse`.
   */
  query: string;
  /** The active filters — passed to the filter rail and action buttons. */
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
  /**
   * Called with a document id when the trace panel's judge-verdict "View"
   * control is activated. Threaded straight through to `SearchTracePanel`.
   */
  onPreview: (documentId: number) => void;
}

/**
 * The zero-result search screen — handles both `"no_match"` and `"clarify"`
 * outcomes and shows the full search trace.
 *
 * Replaces the old screen that showed a single hard-coded message regardless
 * of _why_ the search returned nothing. Now branches on `result.outcome_kind`
 * and `result.no_match_reason` to show a precise, contextual explanation:
 *
 * | outcome_kind | no_match_reason   | filters set? | message                                           | filter actions? |
 * |---|---|---|---|---|
 * | `clarify`    | —                 | —            | the planner's clarify text + caption              | no              |
 * | `no_match`   | `judge_rejected`  | —            | "I found N documents, but none matched…"          | only if filters |
 * | `no_match`   | `empty_retrieval` | yes          | "Your filters narrowed the search to zero…"       | yes             |
 * | `no_match`   | `empty_retrieval` | no           | "Nothing in your library matched that search."    | no              |
 * | `no_match`   | `weak_relevance`  | —            | "The closest matches weren't relevant enough…"    | only if filters |
 *
 * In all cases the component renders the `SearchTracePanel` so the user can
 * inspect the full reasoning trace even when no answer was produced.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, EmptyState, Button,
 * Text, Icon, FilterControls, ActiveFiltersStrip, SearchTracePanel.
 */
export function NoResultsScreen({
  result,
  query,
  filters,
  onFiltersChange,
  onSearch,
  onClearFilters,
  onSearchWithoutFilters,
  onPreview,
}: NoResultsScreenProps): React.ReactElement {
  const { outcome_kind, no_match_reason, candidate_count, answer, trace, cost } = result;
  const filtersActive = hasActiveFilters(filters);

  // ── Derive the copy/actions for this specific zero-result case ──────────────

  type CopyConfig = {
    message: string;
    description?: string;
    showFilterActions: boolean;
  };

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
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Query recap — editable: submitting it re-runs the search with the
            new query, so the user is never stranded on this screen. */}
        <SearchField
          key={query}
          id="no-results-search"
          defaultValue={query}
          onSubmit={onSearch}
        />

        {/* Active-filters summary row (0 documents). Renders nothing when no
            filters are set. */}
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

        {/* Reasoning-trace transparency — the folded per-phase trace with
            per-step and total token/dollar cost. Renders nothing when phases
            is empty (Layer-1 clarify short-circuit with no retrieval). */}
        <SearchTracePanel
          phases={trace.phases}
          cost={cost}
          onPreview={onPreview}
        />

        {/* "Try instead" suggestion block — three canned queries from
            QUICK_FILTERS (shared with IdleScreen). Each row calls onSearch
            so the user navigates directly to a fresh result. */}
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
