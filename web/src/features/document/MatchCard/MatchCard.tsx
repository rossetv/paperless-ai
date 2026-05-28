/**
 * MatchCard — restores the search-context match panel on the document page.
 *
 * When a user navigates to a document from a search result, the URL carries
 * `?q=…` and optionally filter params in `parentSearch`. This card finds the
 * matching `SourceDocument` from the TanStack Query cache (instant if the user
 * navigated from the search page) or re-runs the search once (for cold-loaded
 * shared links). It shows the citation position, relevance score, query text,
 * and the highlighted snippet.
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
  /** The document whose match context we are displaying. */
  documentId: number;
  /** The search query that surfaced this document. */
  query: string;
  /** The active filters at the time of the search. */
  filters: FilterRequest;
}

/**
 * Sidebar card showing where this document appeared in a search result.
 *
 * Renders `null` when `query` is empty — the caller may render this
 * unconditionally when `parent === 'search'`; the empty-query guard ensures
 * no space is taken when there is nothing meaningful to show.
 */
export function MatchCard({
  documentId,
  query,
  filters,
}: MatchCardProps): React.ReactElement | null {
  // Always call the hook (rules of hooks), but pass empty query when there is
  // nothing to search — the hook's own `enabled` gate will short-circuit it.
  const search = useSearch({ query, filters });

  if (query.trim() === '') return null;

  // Show spinner only when there is no data at all (first load / cold share link).
  // `isFetching` without `isPending` means we have cached data being refreshed in
  // the background — we should show the stale data rather than a spinner flash.
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
        <CitationMark index={idx + 1} onActivate={() => {}} />
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
