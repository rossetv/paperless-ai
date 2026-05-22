import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Text } from '../../../components/primitives/Text/Text';
import { FilterControls } from '../FilterControls/FilterControls';
import { AnswerCard } from '../AnswerCard/AnswerCard';
import { SourceList } from '../SourceList/SourceList';
import { QueryPlanSummary } from '../QueryPlanSummary/QueryPlanSummary';
import type { FilterRequest, SearchResponse } from '../../../api/types';

export interface ResultsScreenProps {
  /** The query that produced the result — recapped in the inline field. */
  query: string;
  /** The active filters — passed to the filter rail. */
  filters: FilterRequest;
  /** The resolved search response. */
  result: SearchResponse;
  /** Called when the user changes a filter. */
  onFiltersChange: (filters: FilterRequest) => void;
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
 * AnswerCard, SourceList, QueryPlanSummary. No own CSS module (§12.5 —
 * features layer is composition-only).
 */
export function ResultsScreen({
  query,
  filters,
  result,
  onFiltersChange,
  onCitationActivate,
  onPreview,
  highlightedIndex,
}: ResultsScreenProps): React.ReactElement {
  const { answer, sources, plan, stats } = result;

  return (
    <SearchScreenLayout
      variant="rail"
      rail={
        <FilterControls filters={filters} onFiltersChange={onFiltersChange} />
      }
    >
      <Stack direction="vertical" gap={10}>
        {/* Query recap. */}
        <SearchField
          id="results-search"
          value={query}
          disabled
          onSubmit={() => {}}
        />

        {/* Synthesised answer. */}
        <AnswerCard
          answer={answer}
          sources={sources}
          stats={stats}
          onCitationActivate={onCitationActivate}
        />

        {/* Sources — a real heading carries the role; Text supplies the
            type token (no feature-level CSS, §12.5). */}
        <h2>
          <Text as="span" variant="card-title">
            Sources
          </Text>
        </h2>
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
