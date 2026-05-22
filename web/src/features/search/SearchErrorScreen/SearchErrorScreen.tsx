import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';

export interface SearchErrorScreenProps {
  /** The error detail message to show beneath the headline. */
  message: string;
  /** Called when the user asks to retry — the page re-runs the search. */
  onRetry: () => void;
}

/**
 * The search-failure screen.
 *
 * Shown when a search fails for a reason other than a 503 index-not-ready or
 * a 401 — a 500, a network drop, a malformed response. A centred `EmptyState`
 * reports the failure and offers a "Try again" action. Distinct from
 * `NoResultsScreen`, which is a *successful* search that matched nothing.
 *
 * Composed from: SearchScreenLayout, EmptyState, Button. No own CSS module
 * (§12.5 — features layer is composition-only).
 */
export function SearchErrorScreen({
  message,
  onRetry,
}: SearchErrorScreenProps): React.ReactElement {
  return (
    <SearchScreenLayout variant="centred">
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
    </SearchScreenLayout>
  );
}
