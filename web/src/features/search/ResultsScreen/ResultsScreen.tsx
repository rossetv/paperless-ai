import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Text } from '../../../components/primitives/Text/Text';
import { FilterControls } from '../FilterControls/FilterControls';
import { AnswerCard } from '../AnswerCard/AnswerCard';
import { SourceList } from '../SourceList/SourceList';
import { QueryPlanSummary } from '../QueryPlanSummary/QueryPlanSummary';
import { ActiveFiltersStrip } from '../ActiveFiltersStrip/ActiveFiltersStrip';
import type { FilterRequest, SearchResponse } from '../../../api/types';

export interface ResultsScreenProps {
  /** The query that produced the result — recapped in the inline field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** The resolved search response. */
  result: SearchResponse;
  /**
   * Total matched document count — shown in the active-filters strip.
   * Pass `result.sources.length` when there is no separate total; pass a
   * server-supplied total when available.
   */
  docCount: number;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
  /**
   * Called with a new query when the user submits the recap search field —
   * the parent re-runs the search, so a second search needs no reload.
   */
  onSearch: (query: string) => void;
  /** Called when the user activates "Clear all" in the active-filters strip. */
  onClearFilters: () => void;
  /** Called with a 1-based index when a citation marker is activated. */
  onCitationActivate: (index: number) => void;
  /** Called with a document id when a source's preview action is activated. */
  onPreview: (documentId: number) => void;
  /**
   * 1-based index of the source to highlight, set when a citation is
   * activated. When undefined, no source is highlighted.
   */
  highlightedIndex?: number;
}

/**
 * The search results screen.
 *
 * The rail+content layout: the filter rail, then a query recap, the
 * `AnswerCard` with its inline citations, a "Sources" header, the list of
 * `SourceCard`s, and the `QueryPlanSummary` disclosure. Citation activation
 * and document preview are delegated to the parent via callbacks.
 *
 * Composed from: SearchScreenLayout, Stack, SearchField, Text, FilterControls,
 * AnswerCard, SourceList, QueryPlanSummary, ActiveFiltersStrip. No own CSS
 * module (§12.5 — features layer is composition-only).
 */
export function ResultsScreen({
  query,
  filters,
  result,
  docCount,
  onFiltersChange,
  onSearch,
  onClearFilters,
  onCitationActivate,
  onPreview,
  highlightedIndex,
}: ResultsScreenProps): React.ReactElement {
  const { answer, sources, plan, stats } = result;

  /**
   * Handles a citation activation: highlights the source card AND opens its
   * document preview. The 1-based index maps to `sources[index - 1]`.
   */
  function handleCitationActivate(index: number): void {
    onCitationActivate(index);
    const source = sources[index - 1];
    if (source !== undefined) {
      onPreview(source.document_id);
    }
  }

  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Query recap — editable: submitting it re-runs the search with the
            new query, so a second search needs no browser reload. Keyed by
            `query` so it re-seeds whenever a fresh search lands. */}
        <SearchField
          key={query}
          id="results-search"
          defaultValue={query}
          onSubmit={onSearch}
        />

        {/* Active-filters chip strip — renders nothing when no filters are
            set, so this is safe to include unconditionally. */}
        <ActiveFiltersStrip
          filters={filters}
          docCount={docCount}
          onClearAll={onClearFilters}
        />

        {/* Synthesised answer. */}
        <AnswerCard
          answer={answer}
          sources={sources}
          stats={stats}
          onCitationActivate={handleCitationActivate}
        />

        {/* Sources — a real heading carries the role; sub-heading is the
            22 px display variant matching the design (MAJOR 2). The caption
            sits alongside as a sibling, not inside the <h2>. */}
        <Stack direction="horizontal" gap={6} align="baseline">
          <h2 style={{ margin: 0 }}>
            <Text as="span" variant="sub-heading">
              Sources
            </Text>
          </h2>
          <Text as="span" variant="caption" tone="tertiary">
            the documents that grounded the answer above
          </Text>
        </Stack>

        <SourceList
          sources={sources}
          onPreview={onPreview}
          {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
        />

        {/* Query-plan transparency. */}
        <QueryPlanSummary plan={plan} stats={stats} />
      </Stack>
    </SearchScreenLayout>
  );
}
