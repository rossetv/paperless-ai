import React from 'react';
import { cn } from '../../../lib/cn';
import styles from './MobileTopBar.module.css';

export interface MobileTopBarProps {
  /**
   * Brand / logo area rendered on the leading edge of the bar.
   * Typically the `<Brand>` mark + wordmark wrapped in a router `<Link>`.
   */
  brand: React.ReactNode;
  /**
   * Optional trailing-edge actions — e.g. `UserMenu`, `IndexStatusPill`.
   * When omitted the bar is brand-only.
   */
  actions?: React.ReactNode;
  className?: string;
}

/**
 * Sticky top bar for mobile viewports (< 700 px).
 *
 * Rendered alongside the desktop `NavBar` and swapped purely in CSS, which
 * avoids conditional-render flicker on resize.
 */
export function MobileTopBar({
  brand,
  actions,
  className,
}: MobileTopBarProps): React.ReactElement {
  return (
    <div
      role="banner"
      className={cn(styles['topbar'], className)}
      aria-label="Mobile top bar"
    >
      <div className={styles['inner']}>
        <div className={styles['brand']}>{brand}</div>
        {actions !== undefined && (
          <div className={styles['actions']}>{actions}</div>
        )}
      </div>
    </div>
  );
}
