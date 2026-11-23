import React from 'react';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import styles from './DocumentErrorScreen.module.css';

export interface DocumentErrorScreenProps {
  /** True for a 404; false shows a generic load-failure message. */
  notFound: boolean;
}

/** Error / not-found state for any route that resolves a single document by id. */
export function DocumentErrorScreen({
  notFound,
}: DocumentErrorScreenProps): React.ReactElement {
  return (
    <div className={styles['state']}>
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
    </div>
  );
}
