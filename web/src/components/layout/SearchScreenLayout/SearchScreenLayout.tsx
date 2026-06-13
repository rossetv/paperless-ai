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
  /** Which content shell to render. */
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
  /** The main content. */
  children: React.ReactNode;
  /** Additional class names to merge. */
  className?: string;
}

/**
 * The content shell for the Wave 2 search screens.
 *
 * Sits directly below `AppNavBar`. `centred` gives a single max-width column
 * (the idle and index-not-ready screens); `rail` gives a filter-rail +
 * content two-column grid that stacks on narrow viewports (the loading,
 * results and no-results screens).
 *
 * The optional `header` prop renders a full-width element above the columns
 * so page titles align to the page gutter on all variants.
 *
 * App-agnostic — it knows nothing about search. The screen features supply
 * the rail and the content.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/.
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
