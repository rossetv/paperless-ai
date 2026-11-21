/**
 * Search-context panel on the document page: where this document ranked for
 * the query it was opened from. The search comes from the query cache when the
 * user came from the search page, or is re-run once for a cold-loaded link.
 */
import React from 'react';
import { useSearch } from '../../../api/hooks';
import type { FilterRequest } from '../../../api/types';
import { Card } from '../../../components/primitives/Card/Card';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { SnippetText } from '../../../components/primitives/SnippetText/SnippetText';
import { CitationMark } from '../../../components/primitives/CitationMark/CitationMark';
import styles from './MatchCard.module.css';

export interface MatchCardProps {
  documentId: number;
  /** The search query that surfaced this document. */
  query: string;
  filters: FilterRequest;
}

/** Renders null for an empty query, so the caller can mount it unconditionally. */
export function MatchCard({
  documentId,
  query,
  filters,
}: MatchCardProps): React.ReactElement | null {
  // Called before the empty-query return (rules of hooks); the hook's own
  // `enabled` gate skips an empty query.
  const search = useSearch({ query, filters });

  if (query.trim() === '') return null;

  // Spin only with no data at all; a background refetch keeps showing stale data.
  if (search.isPending) {
    return (
      <Card className={styles['card'] ?? ''}>
        <Spinner size="small" label="Loading match" />
      </Card>
    );
  }

  if (!search.isSuccess) return null;

  const sources = search.data.sources;
  const idx = sources.findIndex((s) => s.document_id === documentId);

  if (idx === -1) {
    return (
      <Card className={styles['card'] ?? ''}>
        <p className={styles['empty']}>
          This document didn't appear in the results for "{query}".
        </p>
      </Card>
    );
  }

  const src = sources[idx];
  if (src === undefined) return null;

  return (
    <Card className={`${styles['card'] ?? ''} ${styles['card-match'] ?? ''}`}>
      <div className={styles['header']}>
        <CitationMark index={idx + 1} />
        <span className={styles['meta']}>
          <strong>Source {idx + 1} of {sources.length}</strong>
          {' · relevance '}{src.score.toFixed(2)}
          {' · query '}<i>"{query}"</i>
        </span>
      </div>
      {src.snippet !== '' && (
        <div className={styles['snippet']}>
          <SnippetText text={src.snippet} />
        </div>
      )}
    </Card>
  );
}
