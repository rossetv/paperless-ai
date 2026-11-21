import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import styles from './BottomTabBar.module.css';

/** A single tab in the bottom navigation bar. */
export interface BottomTabItem {
  to: string;
  /** Visible label beneath the icon. */
  label: string;
  icon: IconName;
  /**
   * Match the route exactly, so `/` does not match `/library` (React Router's `end`).
   * Typed `boolean | undefined` for `exactOptionalPropertyTypes`.
   */
  end?: boolean | undefined;
}

export interface BottomTabBarProps {
  /**
   * The tab definitions to render. Typically the filtered `NAV_LINKS` from
   * `AppNavBar` (with `adminOnly` items already removed for non-admin users).
   */
  items: BottomTabItem[];
  className?: string;
}

/**
 * Fixed bottom navigation bar for mobile viewports (< 700 px).
 *
 * Rendered alongside the desktop `NavBar`; CSS alone decides which one shows.
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
              <Icon
                name={item.icon}
                size="medium"
                className={cn(styles['tab-icon'])}
                {...(isActive ? { label: `${item.label} (current)` } : {})}
              />
              <span className={styles['tab-label']}>{item.label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
