import React from 'react';
import { cn } from '../../../lib/cn';
import { Icon } from '../Icon/Icon';
import styles from './RecentSearchStrip.module.css';

/** One recent-search row. */
export interface RecentSearchItem {
  /** The recent query text. */
  query: string;
  /** A human-readable relative time, e.g. "2h ago". */
  time: string;
}

export interface RecentSearchStripProps {
  /** The recent searches, newest first. */
  items: RecentSearchItem[];
  /** Called with the query string when a row is activated. */
  onSelect: (query: string) => void;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * A card listing the user's recent searches.
 *
 * Each row is a `<button>` carrying the query, a relative time and a
 * chevron; activating it calls `onSelect` with the query. Renders `null`
 * when there are no items, so the idle screen can drop it unconditionally.
 *
 * App-agnostic: it knows query strings and times, nothing about the search
 * API. The `IdleScreen` feature maps the API response onto `items`.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3). Allowed deps:
 * primitives (Icon), lib/.
 */
export function RecentSearchStrip({
  items,
  onSelect,
  className,
}: RecentSearchStripProps): React.ReactElement | null {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className={cn(styles['strip'], className)}>
      <p className={styles['heading']}>Recent searches</p>
      <div className={styles['rows']}>
        {items.map((item, i) => (
          <button
            key={i}
            type="button"
            className={styles['row']}
            onClick={() => onSelect(item.query)}
          >
            <span className={styles['chevron']} aria-hidden="true">
              <Icon name="search" size="small" />
            </span>
            <span className={styles['query']}>{item.query}</span>
            <span className={styles['time']}>{item.time}</span>
            <span className={styles['chevron']} aria-hidden="true">
              <Icon name="chevron-right" size="small" />
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
