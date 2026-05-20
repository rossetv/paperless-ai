import React from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Stack } from '../../../components/layout/Stack/Stack';
import { ApiError, Unauthenticated } from '../../../api/client';
import type { SearchResponse } from '../../../api/types';
import { AnswerCard } from '../AnswerCard/AnswerCard';
import { SourceList } from '../SourceList/SourceList';
import { QueryPlanSummary } from '../QueryPlanSummary/QueryPlanSummary';

export interface SearchResultsProps {
  /**
   * The current search query. When empty the results area is idle (renders
   * nothing) — the search hook is disabled and carries no meaningful state.
   */
  query: string;
  /**
   * The TanStack Query result for the active search. SearchResults inspects its
   * status to pick the right state to render.
   */
  result: UseQueryResult<SearchResponse, Error>;
  /** Called with a 1-based citation index when a citation marker is activated. */
  onCitationActivate: (index: number) => void;
  /**
   * 1-based index of the source to highlight, set when a citation is activated.
   * When undefined, no source is highlighted.
   */
  highlightedIndex?: number;
}

/**
 * Returns true when the error indicates the search index has not yet finished
 * building — the server sends a 503 with the detail "index-not-ready".
 */
function isIndexNotReady(error: Error): boolean {
  return error instanceof ApiError && error.status === 503;
}

/**
 * The search results area — owns every result-state presentation.
 *
 * Renders one of: idle (nothing) / loading (Spinner) / index-initialising /
 * search-failed / no-results / success (AnswerCard + SourceList +
 * QueryPlanSummary).
 *
 * This is the search-domain feature that composes the loading and empty-state
 * primitives. A page may not reach a `Spinner` primitive or an `EmptyState`
 * pattern directly (§12.3) — it composes this feature instead. An
 * `Unauthenticated` error is left for the page to act on (it routes to login);
 * SearchResults simply renders nothing for that case.
 *
 * Composed from: Spinner, EmptyState, Stack, AnswerCard, SourceList,
 * QueryPlanSummary. No own CSS module (§12.5 — features layer is
 * composition-only).
 */
export function SearchResults({
  query,
  result,
  onCitationActivate,
  highlightedIndex,
}: SearchResultsProps): React.ReactElement | null {
  // Idle: no query submitted yet.
  if (query.trim().length === 0) {
    return null;
  }

  // Loading: a request is in flight.
  if (result.isPending || result.isFetching) {
    return <Spinner label="Searching…" size="large" />;
  }

  // Error: distinguish 503 index-not-ready from other failures. An
  // Unauthenticated error renders nothing — the page routes to the login screen.
  if (result.isError && result.error !== null) {
    if (isIndexNotReady(result.error)) {
      return (
        <EmptyState
          icon="info"
          message="The index is initialising"
          description="The search index is still being built. Try again in a moment."
        />
      );
    }
    if (!(result.error instanceof Unauthenticated)) {
      return (
        <EmptyState
          icon="warning"
          message="Search failed"
          description={result.error.message}
        />
      );
    }
    return null;
  }

  // Success.
  if (result.isSuccess && result.data !== undefined) {
    const { answer, sources, plan, stats } = result.data;

    // Empty result: the pipeline returned nothing.
    if (sources.length === 0) {
      return (
        <EmptyState
          icon="search"
          message="No results found"
          description="Try adjusting your query or removing some filters."
        />
      );
    }

    return (
      <Stack direction="vertical" gap={8}>
        <AnswerCard
          answer={answer}
          sources={sources}
          onCitationActivate={onCitationActivate}
        />
        <SourceList
          sources={sources}
          {...(highlightedIndex !== undefined ? { highlightedIndex } : {})}
        />
        <QueryPlanSummary plan={plan} stats={stats} />
      </Stack>
    );
  }

  return null;
}
