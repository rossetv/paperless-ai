import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './IndexStatusFooter.module.css';

export interface IndexStatusFooterProps {
  /** Total indexed documents. */
  documentCount: number;
  /** Total semantic chunks. */
  chunkCount: number;
  /** The embedding model name, or null when unknown. */
  embeddingModel: string | null;
  /** Additional class names to merge. */
  className?: string;
}

/** Group digits with thousands separators for readability. */
function groupDigits(value: number): string {
  return value.toLocaleString('en-GB');
}

/**
 * The index-status summary line for the search idle screen.
 *
 * A ready dot plus "Index ready", the document and chunk counts, and the
 * embedding model (omitted when unknown). Presentational — it formats the
 * figures it is given and knows nothing about the stats API.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function IndexStatusFooter({
  documentCount,
  chunkCount,
  embeddingModel,
  className,
}: IndexStatusFooterProps): React.ReactElement {
  return (
    <div className={cn(styles['footer'], className)}>
      <span className={styles['status']}>
        <span className={styles['dot']} aria-hidden="true" />
        Index ready
      </span>
      <span>
        {groupDigits(documentCount)} documents · {groupDigits(chunkCount)} chunks
      </span>
      {embeddingModel !== null && <span>{embeddingModel}</span>}
    </div>
  );
}
