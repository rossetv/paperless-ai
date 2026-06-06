import React from 'react';
import { Stack } from '../../../components/layout/Stack/Stack';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from '../SourceCard/SourceCard';
import styles from './SourceList.module.css';

export interface SourceListProps {
  /** Ordered list of source documents from the search response. */
  sources: SourceDocument[];
  /**
   * 1-based index of the source to highlight (matches a CitationLink index).
   * When undefined, no source is highlighted.
   */
  highlightedIndex?: number;
  /**
   * Called with a document id when a source card's "Preview" action
   * is activated. Threaded straight through to every `SourceCard`.
   */
  onPreview: (documentId: number) => void;
}

/**
 * Ordered list of SourceCards.
 *
 * Renders each source with its 1-based citation index so users can
 * cross-reference the [n] markers in the AnswerCard.
 *
 * Shows an EmptyState when there are no sources to display.
 *
 * Composed from: Stack, EmptyState, SourceCard.
 * Own CSS module resets browser list defaults so global.css list styles do not bleed.
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
    <Stack direction="vertical" gap={6}>
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
    </Stack>
  );
}
