import React, { useId, useState } from 'react';
import { Icon } from '../../primitives/Icon/Icon';
import { cn } from '../../../lib/cn';
import styles from './FilterPanel.module.css';

export interface FilterPanelProps {
  /** Title rendered in the panel header, next to the collapse toggle. */
  title: string;
  /** Panel content — rendered when expanded. */
  children: React.ReactNode;
  /** Whether the panel is initially expanded. Defaults to true. */
  defaultExpanded?: boolean;
  /** Additional class names to merge onto the root element. */
  className?: string;
}

/**
 * Collapsible panel container — generic titled wrapper that expands/collapses
 * its children on demand.
 *
 * Accessibility:
 * - The toggle button carries aria-expanded on every render.
 * - aria-controls points to the content region id so screen readers
 *   can announce the relationship.
 *
 * App-agnostic — carries no knowledge of search, documents, or filters.
 * The caller provides the content and the title.
 *
 * Composes the Icon primitive for the chevron toggle indicator.
 */
export function FilterPanel({
  title,
  children,
  defaultExpanded = true,
  className,
}: FilterPanelProps): React.ReactElement {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const autoId = useId();
  const contentId = `filter-panel-content-${autoId}`;

  function toggle(): void {
    setIsExpanded((prev) => !prev);
  }

  const rootClasses = cn(styles['filter-panel'], className);

  return (
    <div className={rootClasses}>
      <button
        type="button"
        aria-expanded={isExpanded}
        aria-controls={contentId}
        className={styles['toggle']}
        onClick={toggle}
      >
        <span className={styles['title']}>{title}</span>
        <span
          className={cn(styles['chevron'], isExpanded ? styles['expanded'] : undefined)}
          aria-hidden="true"
        >
          <Icon name="chevron-down" size="small" />
        </span>
      </button>

      {isExpanded && (
        <div id={contentId} className={styles['content']}>
          {children}
        </div>
      )}
    </div>
  );
}
