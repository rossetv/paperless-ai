import React from 'react';
import { Text } from '../../../components/primitives/Text/Text';
import { Button } from '../../../components/primitives/Button/Button';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { useFacets } from '../../../api/hooks';
import type { FilterRequest } from '../../../api/types';
import { hasActiveFilters } from '../filters';
import styles from './ActiveFiltersStrip.module.css';

export interface ActiveFiltersStripProps {
  filters: FilterRequest;
  /** Matching document count; 0 on the no-results screen. */
  docCount: number;
  onClearAll: () => void;
}

/**
 * One chip per active filter, plus "Clear all" and the document count.
 * Renders nothing when no filter is set, so callers can render it
 * unconditionally. `useFacets` is already cached by FilterControls, so name
 * resolution costs no extra request.
 */
export function ActiveFiltersStrip({
  filters,
  docCount,
  onClearAll,
}: ActiveFiltersStripProps): React.ReactElement | null {
  const { data: facets } = useFacets();

  if (!hasActiveFilters(filters)) {
    return null;
  }

  // Keyed by filter dimension, not index, so adding or removing a filter does
  // not remount the other chips.
  const chips: Array<{ key: string; label: string }> = [];

  if (filters.correspondent_id != null && facets !== undefined) {
    const match = facets.correspondents.find((c) => c.id === filters.correspondent_id);
    if (match !== undefined) chips.push({ key: 'correspondent', label: match.name });
  }

  if (filters.document_type_id != null && facets !== undefined) {
    const match = facets.document_types.find((d) => d.id === filters.document_type_id);
    if (match !== undefined) chips.push({ key: 'type', label: match.name });
  }

  if (facets !== undefined) {
    for (const tagId of filters.tag_ids) {
      const match = facets.tags.find((t) => t.id === tagId);
      if (match !== undefined) chips.push({ key: `tag-${tagId}`, label: match.name });
    }
  } else {
    // Facets not loaded yet: placeholder chips still show that tags are set.
    for (const tagId of filters.tag_ids) {
      chips.push({ key: `tag-${tagId}`, label: '…' });
    }
  }

  if (filters.date_from != null || filters.date_to != null) {
    const from = filters.date_from ?? '…';
    const to = filters.date_to ?? '…';
    chips.push({ key: 'date', label: `${from} – ${to}` });
  }

  return (
    <div className={styles['strip']} role="region" aria-label="Active filters">
      {/* "Filtered by" label */}
      <Text as="span" variant="caption" tone="secondary">
        Filtered by
      </Text>

      {chips.map(({ key, label }) => (
        <Chip key={key} selected>
          {label}
        </Chip>
      ))}

      {/* Clear all */}
      <Button variant="ghost" size="small" onClick={onClearAll}>
        Clear all
      </Button>

      <span className={styles['spacer']} />

      {/* The class sits on the outer span; Text takes no className under
          exactOptionalPropertyTypes. */}
      <span className={styles['count']}>
        <Text as="span" variant="caption">
          <strong>{docCount.toLocaleString('en-GB')} {docCount === 1 ? 'document' : 'documents'}</strong>
          {' · sorted by relevance'}
        </Text>
      </span>
    </div>
  );
}
