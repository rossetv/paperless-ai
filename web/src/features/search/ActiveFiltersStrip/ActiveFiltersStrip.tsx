import React from 'react';
import { Text } from '../../../components/primitives/Text/Text';
import { Button } from '../../../components/primitives/Button/Button';
import { Chip } from '../../../components/primitives/Chip/Chip';
import { useFacets } from '../../../api/hooks';
import type { FilterRequest } from '../../../api/types';
import styles from './ActiveFiltersStrip.module.css';

export interface ActiveFiltersStripProps {
  /** The currently active filters — used to derive chip labels. */
  filters: FilterRequest;
  /**
   * Total number of matching documents. Pass 0 on the no-results screen.
   * Rendered as "<N> documents · sorted by relevance".
   */
  docCount: number;
  /** Called when the user activates "Clear all". */
  onClearAll: () => void;
}

/** Returns true when at least one filter value is set. */
function hasActiveFilters(filters: FilterRequest): boolean {
  return (
    filters.tag_ids.length > 0 ||
    filters.correspondent_id != null ||
    filters.document_type_id != null ||
    filters.date_from != null ||
    filters.date_to != null
  );
}

/**
 * Active-filters chip strip.
 *
 * Rendered between the recap SearchField and the main content area whenever
 * at least one filter is active. Shows a "Filtered by" label, one selected
 * Chip per active filter, a "Clear all" link, and a trailing document count.
 *
 * Name resolution uses `useFacets` — the query is already cached by
 * FilterControls, so this never triggers a second network request.
 *
 * Renders nothing when no filters are active, so callers can render it
 * unconditionally.
 *
 * Composed from: Stack, Text, Chip. No layout CSS beyond the strip flex row.
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

  // Build a flat list of active filter labels to render as chips.
  const chips: string[] = [];

  if (filters.correspondent_id != null && facets !== undefined) {
    const match = facets.correspondents.find((c) => c.id === filters.correspondent_id);
    if (match !== undefined) chips.push(match.name);
  }

  if (filters.document_type_id != null && facets !== undefined) {
    const match = facets.document_types.find((d) => d.id === filters.document_type_id);
    if (match !== undefined) chips.push(match.name);
  }

  if (facets !== undefined) {
    for (const tagId of filters.tag_ids) {
      const match = facets.tags.find((t) => t.id === tagId);
      if (match !== undefined) chips.push(match.name);
    }
  } else {
    // Facets not yet loaded — show placeholder chip counts so the strip
    // still communicates that filters are set.
    for (let i = 0; i < filters.tag_ids.length; i++) {
      chips.push('…');
    }
  }

  if (filters.date_from != null || filters.date_to != null) {
    const from = filters.date_from ?? '…';
    const to = filters.date_to ?? '…';
    chips.push(`${from} – ${to}`);
  }

  return (
    <div className={styles['strip']} role="region" aria-label="Active filters">
      {/* "Filtered by" label — caption variant, secondary tone. */}
      <Text as="span" variant="caption" tone="secondary">
        Filtered by
      </Text>

      {chips.map((label, i) => (
        <Chip key={i} selected>
          {label}
        </Chip>
      ))}

      {/* Clear all — ghost Button carries the token-based focus ring. */}
      <Button variant="ghost" size="small" onClick={onClearAll}>
        Clear all
      </Button>

      <span className={styles['spacer']} />

      {/* Document count — outer span holds the class; Text renders without
          a className so exactOptionalPropertyTypes is satisfied. */}
      <span className={styles['count']}>
        <Text as="span" variant="caption">
          <strong>{docCount.toLocaleString('en-GB')} {docCount === 1 ? 'document' : 'documents'}</strong>
          {' · sorted by relevance'}
        </Text>
      </span>
    </div>
  );
}
