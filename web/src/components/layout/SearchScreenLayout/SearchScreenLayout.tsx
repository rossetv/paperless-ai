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
 * App-agnostic — it knows nothing about search. The screen features supply
 * the rail and the content.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/.
 */
export function SearchScreenLayout({
  variant,
  rail,
  children,
  className,
}: SearchScreenLayoutProps): React.ReactElement {
  return (
    <div className={cn(styles['layout'], styles[variant], className)}>
      {variant === 'rail' && (
        <div className={styles['rail-region']} data-screen-rail>
          {rail}
        </div>
      )}
      <div className={styles['content-region']}>{children}</div>
    </div>
  );
}
