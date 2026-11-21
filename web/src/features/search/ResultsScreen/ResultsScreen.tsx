import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { Stack } from '../../../components/layout/Stack/Stack';
import { SearchField } from '../../../components/patterns/SearchField/SearchField';
import { Text } from '../../../components/primitives/Text/Text';
import { FilterControls } from '../../../components/patterns/FilterControls/FilterControls';
import { AnswerCard } from '../AnswerCard/AnswerCard';
import { SourceList } from '../SourceList/SourceList';
import { SearchTracePanel } from '../SearchTracePanel/SearchTracePanel';
import { ActiveFiltersStrip } from '../ActiveFiltersStrip/ActiveFiltersStrip';
import type { FilterRequest, SearchResponse } from '../../../api/types';
import styles from './ResultsScreen.module.css';

export interface ResultsScreenProps {
  query: string;
  filters: FilterRequest;
  result: SearchResponse;
  /** Matched document count for the active-filters strip. */
  docCount: number;
  onFiltersChange: (filters: FilterRequest) => void;
  onSearch: (query: string) => void;
  onClearFilters: () => void;
  /** Called with the 1-based index of the activated citation. */
  onCitationActivate: (index: number) => void;
  onPreview: (documentId: number) => void;
  /** 1-based index of the source to highlight after a citation is activated. */
  highlightedIndex?: number;
}

/** The search results screen: answer, sources and the folded search trace. */
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
  const { answer, sources, stats, cost, trace, outcome_kind } = result;
  const isAnswered = outcome_kind === 'answered';

  /** A citation both highlights its source card and opens its preview. */
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
        {/* Keyed by `query` so it re-seeds whenever a fresh search lands. */}
        <SearchField
          key={query}
          id="results-search"
          defaultValue={query}
          onSubmit={onSearch}
        />

        {/* Active filters */}
        <ActiveFiltersStrip
          filters={filters}
          docCount={docCount}
          onClearAll={onClearFilters}
        />

        {/* Answer, or a retry nudge for clarify/no_match */}
        <AnswerCard
          answer={answer}
          sources={sources}
          stats={stats}
          cost={cost}
          outcomeKind={outcome_kind}
          onCitationActivate={handleCitationActivate}
        />

        {/* For clarify/no_match sources are empty and the nudge card says what to do. */}
        {isAnswered && (
          <>
            {/* The caption is a sibling of the <h2>, not part of the heading. */}
            <Stack direction="horizontal" gap={6} align="baseline">
              <h2 className={styles['sources-heading']}>
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
          </>
        )}

        {/* Search trace */}
        <SearchTracePanel
          phases={trace.phases}
          cost={cost}
          onPreview={onPreview}
        />
      </Stack>
    </SearchScreenLayout>
  );
}
