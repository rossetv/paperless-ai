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
  /** Additional class names to merge onto the root element. */
  className?: string;
}

/**
 * Sticky top bar for mobile viewports (< 700 px).
 *
 * Implements the mediaman `nav-topbar` pattern: 48 px high, glass background,
 * brand on the left and optional action slots on the right. Hidden at ≥ 700 px
 * via media query — the desktop `NavBar` takes over above that breakpoint.
 *
 * Both `MobileTopBar` and `NavBar` are rendered into the DOM simultaneously;
 * the surface swap is purely CSS `display: none / flex`. This avoids any
 * conditional-render flicker on resize and keeps server-rendered HTML stable.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/.
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
