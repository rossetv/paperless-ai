import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';

export interface IndexNotReadyScreenProps {
  /** Called when the user asks to retry — the page re-runs the last search. */
  onRetry: () => void;
}

/**
 * Shown when a search returns 503 because the index is still being built for
 * the first time. There is no indexing-progress endpoint, so it explains the
 * wait rather than showing progress.
 */
export function IndexNotReadyScreen({
  onRetry,
}: IndexNotReadyScreenProps): React.ReactElement {
  return (
    <SearchScreenLayout variant="centred">
      <EmptyState
        icon="info"
        message="The index is initialising."
        description="We're embedding your library for the first time. Search will be ready once reconciliation completes — for a large archive this can take a few hours."
        action={
          <Button variant="primary" onClick={onRetry}>
            Retry now
          </Button>
        }
      />
    </SearchScreenLayout>
  );
}
