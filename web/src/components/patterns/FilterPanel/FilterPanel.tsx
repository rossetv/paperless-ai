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
  /** Called with the new state when the toggle is used. */
  onExpandedChange?: (expanded: boolean) => void;
  className?: string;
}

/**
 * Collapsible titled panel. The toggle carries aria-expanded and aria-controls
 * pointing at the content region.
 */
export function FilterPanel({
  title,
  children,
  defaultExpanded = true,
  onExpandedChange,
  className,
}: FilterPanelProps): React.ReactElement {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const autoId = useId();
  const contentId = `filter-panel-content-${autoId}`;

  function toggle(): void {
    setIsExpanded(!isExpanded);
    onExpandedChange?.(!isExpanded);
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
