import React from 'react';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';

export interface LibraryDocumentErrorScreenProps {
  /**
   * When true, the document was not found (404); renders a "Document not found"
   * message. When false, a generic load-failure message is shown.
   */
  notFound: boolean;
}

/**
 * Error / not-found state for the `LibraryDocumentPage` route.
 *
 * Wraps `EmptyState` so that the `pages` layer is not required to reach
 * directly into `components/patterns` (CODE_GUIDELINES §12.3). Two variants:
 *
 * - **not found (404)**: the document has been deleted or was never indexed.
 * - **load failure**: a transient error; the user is invited to retry.
 *
 * Tier: features/library (CODE_GUIDELINES §12.3) — composes the EmptyState
 * pattern primitive, nothing from api or other features.
 */
export function LibraryDocumentErrorScreen({
  notFound,
}: LibraryDocumentErrorScreenProps): React.ReactElement {
  return (
    <EmptyState
      icon={notFound ? 'search' : 'warning'}
      message={notFound ? 'Document not found' : 'Could not load document'}
      description={
        notFound
          ? 'This document is no longer in the index.'
          : 'The document is unavailable. Try again in a moment.'
      }
    />
  );
}
