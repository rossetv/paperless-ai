import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import styles from './BottomTabBar.module.css';

/** A single tab in the bottom navigation bar. */
export interface BottomTabItem {
  /** React Router target path. */
  to: string;
  /** Visible label beneath the icon. */
  label: string;
  /** Icon to render above the label. */
  icon: IconName;
  /**
   * When `true`, the tab only matches its route exactly — prevents `/` matching
   * `/library`. Mirror of React Router's `end` prop on `<NavLink>`.
   * Explicitly typed as `boolean | undefined` to satisfy `exactOptionalPropertyTypes`.
   */
  end?: boolean | undefined;
  /**
   * When `true`, this tab should only be shown to admin users.
   * Filtering is the caller's responsibility — the component renders
   * whatever items it receives.
   */
  adminOnly?: boolean | undefined;
}

export interface BottomTabBarProps {
  /**
   * The tab definitions to render. Typically the filtered `NAV_LINKS` from
   * `AppNavBar` (with `adminOnly` items already removed for non-admin users).
   */
  items: BottomTabItem[];
  /** Additional class names to merge onto the root element. */
  className?: string;
}

/**
 * Fixed bottom navigation bar for mobile viewports (< 700 px).
 *
 * Renders a row of stacked icon + label tabs using the glass-navigation
 * treatment (--colour-nav-bg + --backdrop-nav). Each tab is a React Router
 * `NavLink` that receives an `active` class when its route is current.
 *
 * Hidden at ≥ 700 px via media query — both the desktop `NavBar` and this
 * component are rendered into the DOM simultaneously; the surface swap is
 * purely CSS `display: none / flex`.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * components/primitives, react-router-dom.
 */
export function BottomTabBar({
  items,
  className,
}: BottomTabBarProps): React.ReactElement {
  return (
    <nav
      className={cn(styles['bar'], className)}
      aria-label="Mobile navigation"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end === true}
          className={({ isActive }) =>
            cn(styles['tab'], isActive && styles['tab-active'])
          }
        >
          {({ isActive }) => (
            <>
              {isActive ? (
                <Icon
                  name={item.icon}
                  size="medium"
                  className={cn(styles['tab-icon'])}
                  label={`${item.label} (current)`}
                />
              ) : (
                <Icon
                  name={item.icon}
                  size="medium"
                  className={cn(styles['tab-icon'])}
                />
              )}
              <span className={styles['tab-label']}>{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
