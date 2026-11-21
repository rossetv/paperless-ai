import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './SearchScreenLayout.module.css';

/**
 * Content-shell variant.
 * - `centred` — a single max-width centred column.
 * - `rail`    — a filter-rail + content two-column grid.
 */
export type SearchScreenVariant = 'centred' | 'rail';

export interface SearchScreenLayoutProps {
  variant: SearchScreenVariant;
  /**
   * The filter-rail content. Required for the `rail` variant; ignored for
   * `centred`.
   */
  rail?: React.ReactNode;
  /**
   * Optional full-width header rendered above the rail/content columns.
   * Spans both grid columns in the `rail` variant so it aligns to the page
   * gutter rather than the content column edge.
   */
  header?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

/**
 * Content shell for the search screens, below `AppNavBar`.
 *
 * `centred` is a single max-width column (idle, index not ready); `rail` is a
 * filter rail plus content grid that stacks on narrow viewports (loading,
 * results, no results).
 */
export function SearchScreenLayout({
  variant,
  rail,
  header,
  children,
  className,
}: SearchScreenLayoutProps): React.ReactElement {
  return (
    <div className={cn(styles['layout'], styles[variant], className)}>
      {header !== undefined && (
        <div className={styles['header-region']}>{header}</div>
      )}
      {variant === 'rail' && (
        <div className={styles['rail-region']} data-screen-rail>
          {rail}
        </div>
      )}
      <div className={styles['content-region']}>{children}</div>
    </div>
  );
}
