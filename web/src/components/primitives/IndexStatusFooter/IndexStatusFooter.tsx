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
  className?: string;
}

function groupDigits(value: number): string {
  return value.toLocaleString('en-GB');
}

/**
 * Index-status line for the search idle screen: a ready dot, the document and
 * chunk counts, and the embedding model when known.
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
