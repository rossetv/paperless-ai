import React from 'react';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';

export interface DocumentErrorScreenProps {
  /** True for a 404; false shows a generic load-failure message. */
  notFound: boolean;
}

/** Error / not-found state for any route that resolves a single document by id. */
export function DocumentErrorScreen({
  notFound,
}: DocumentErrorScreenProps): React.ReactElement {
  return (
    <EmptyState
      icon={notFound ? 'search' : 'warning'}
      messageAs="h1"
      message={notFound ? 'Document not found' : 'Could not load document'}
      description={
        notFound
          ? 'This document is no longer in the index.'
          : 'The document is unavailable. Try again in a moment.'
      }
    />
  );
}
