import React from 'react';
import { NavLink } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import styles from './SettingsSideNav.module.css';

/** A single navigable item in a {@link SettingsNavGroup}. */
export interface SettingsNavItem {
  /** Stable identifier — used for React keys, never displayed. */
  id: string;
  /** Visible link label. */
  label: string;
  /** Route path the link navigates to. */
  to: string;
}

/**
 * A titled group of settings nav items.
 *
 * Wave 3 supplies one group ("Access Control"). Wave 4 adds a second
 * ("Configuration") simply by passing another group object — the component
 * needs no change.
 */
export interface SettingsNavGroup {
  /** Uppercase group heading. */
  title: string;
  /** The items in this group, top-to-bottom. */
  items: SettingsNavItem[];
}

export interface SettingsSideNavProps {
  /** The groups to render, top-to-bottom. */
  groups: SettingsNavGroup[];
  /** Additional class names to merge onto the `<nav>`. */
  className?: string;
}

/**
 * The left navigation rail of the settings / access-control area.
 *
 * Fully data-driven: it renders whatever `groups` it is given. Each item is
 * a `NavLink`, so the link matching the current route is styled active and
 * gets `aria-current="page"` for free. Holds no domain knowledge — the
 * consuming layout supplies the groups.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * react-router-dom.
 */
export function SettingsSideNav({
  groups,
  className,
}: SettingsSideNavProps): React.ReactElement {
  return (
    <nav className={cn(styles['nav'], className)} aria-label="Settings">
      {groups.map((group) => (
        <div key={group.title} className={styles['group']}>
          <span className={styles['groupTitle']}>{group.title}</span>
          {group.items.map((item) => (
            <NavLink
              key={item.id}
              to={item.to}
              className={({ isActive }) =>
                cn(styles['link'], isActive && styles['linkActive'])
              }
              end
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}
