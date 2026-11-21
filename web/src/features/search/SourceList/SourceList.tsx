import React from 'react';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from '../SourceCard/SourceCard';
import styles from './SourceList.module.css';

export interface SourceListProps {
  sources: SourceDocument[];
  /** 1-based index of the source to highlight, matching a CitationMark. */
  highlightedIndex?: number;
  onPreview: (documentId: number) => void;
}

/**
 * Ordered SourceCards, each numbered with its 1-based citation index so it
 * lines up with the [n] markers in the AnswerCard.
 */
export function SourceList({
  sources,
  highlightedIndex,
  onPreview,
}: SourceListProps): React.ReactElement {
  if (sources.length === 0) {
    return (
      <EmptyState
        icon="document"
        message="No sources found"
        description="Try adjusting your query or filters to find relevant documents."
      />
    );
  }

  return (
    <ol className={styles['list']} aria-label="Sources">
      {sources.map((source, i) => {
        const index = i + 1;
        return (
          <li key={source.document_id} className={styles['item']}>
            <SourceCard
              source={source}
              index={index}
              highlighted={highlightedIndex === index}
              onPreview={onPreview}
            />
          </li>
        );
      })}
    </ol>
  );
}
