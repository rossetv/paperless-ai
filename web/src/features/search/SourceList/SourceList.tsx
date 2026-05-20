import React from 'react';
import { Stack } from '../../../components/layout/Stack/Stack';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from '../SourceCard/SourceCard';

export interface SourceListProps {
  /** Ordered list of source documents from the search response. */
  sources: SourceDocument[];
  /**
   * 1-based index of the source to highlight (matches a CitationLink index).
   * When undefined, no source is highlighted.
   */
  highlightedIndex?: number;
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
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function SourceList({
  sources,
  highlightedIndex,
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
      <ol>
        {sources.map((source, i) => {
          const index = i + 1;
          return (
            <li key={source.document_id}>
              <SourceCard
                source={source}
                index={index}
                highlighted={highlightedIndex === index}
              />
            </li>
          );
        })}
      </ol>
    </Stack>
  );
}
