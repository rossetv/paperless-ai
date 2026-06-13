import React, { useState } from 'react';
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
  /**
   * Called when the user activates the "Clear" affordance.
   * When omitted the Clear button is not rendered.
   */
  onClear?: () => void;
  /** Additional class names to merge. */
  className?: string;
}

/** Maximum number of rows visible before the "Show more" toggle appears. */
const DEFAULT_CAP = 8;

/**
 * A card listing the user's recent searches.
 *
 * Each row is a `<button>` carrying the query, a relative time and a
 * chevron; activating it calls `onSelect` with the query. Renders `null`
 * when there are no items, so the idle screen can drop it unconditionally.
 *
 * When more than `DEFAULT_CAP` items are supplied only the first `DEFAULT_CAP`
 * are shown; a "Show more" / "Show less" toggle expands the full list.
 * When `onClear` is provided a "Clear" affordance appears in the heading row.
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
  onClear,
  className,
}: RecentSearchStripProps): React.ReactElement | null {
  const [showAll, setShowAll] = useState(false);

  if (items.length === 0) {
    return null;
  }

  const hasMore = items.length > DEFAULT_CAP;
  const visible = hasMore && !showAll ? items.slice(0, DEFAULT_CAP) : items;

  return (
    <div className={cn(styles['strip'], className)}>
      <div className={styles['heading-row']}>
        <p className={styles['heading']}>Recent searches</p>
        {onClear !== undefined && (
          <button
            type="button"
            className={styles['clear-btn']}
            onClick={onClear}
          >
            Clear
          </button>
        )}
      </div>
      <div className={styles['rows']}>
        {visible.map((item) => (
          <button
            key={item.query}
            type="button"
            className={styles['row']}
            onClick={() => onSelect(item.query)}
          >
            <span className={styles['icon']} aria-hidden="true">
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
      {hasMore && (
        <button
          type="button"
          className={styles['show-more']}
          onClick={() => setShowAll((prev) => !prev)}
        >
          {showAll ? 'Show less' : `Show ${items.length - DEFAULT_CAP} more`}
        </button>
      )}
    </div>
  );
}
