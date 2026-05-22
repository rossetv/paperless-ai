import React from 'react';
import { SearchScreenLayout } from '../../../components/layout/SearchScreenLayout/SearchScreenLayout';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { Button } from '../../../components/primitives/Button/Button';

export interface IndexNotReadyScreenProps {
  /** Called when the user asks to retry — the page re-runs the last search. */
  onRetry: () => void;
}

/**
 * The search index-not-ready screen.
 *
 * Shown when a search returns 503 because the index is still being built for
 * the first time. A centred `EmptyState` explains the wait and offers a
 * "Retry now" action; the retry is delegated to the parent.
 *
 * The handoff also sketches a live progress bar, but the search server
 * publishes no indexing-progress endpoint in Wave 2 (that is Wave 6's
 * daemon-status work) — so this screen shows the explanatory state only.
 *
 * Composed from: SearchScreenLayout, EmptyState, Button. No own CSS module
 * (§12.5 — features layer is composition-only).
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
