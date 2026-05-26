import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import styles from './SettingsSideNav.module.css';

/** A single navigable item in a {@link SettingsNavGroup}. */
export interface SettingsNavItem {
  /** Stable identifier — used for React keys, never displayed. */
  id: string;
  /** Visible link label. */
  label: string;
  /** Route path the link navigates to. */
  to: string;
  /** Optional icon shown to the left of the label. */
  icon?: IconName;
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
  /**
   * Optional eyebrow text shown at the very top of the rail, above the first
   * group — e.g. "SETTINGS".
   */
  eyebrow?: string;
  /** Additional class names to merge onto the `<nav>`. */
  className?: string;
}

/**
 * The left navigation rail of the settings / access-control area.
 *
 * Fully data-driven: it renders whatever `groups` it is given. Each item is
 * a `NavLink` (routed pages) or a plain `<a>` (in-page anchors). An optional
 * `eyebrow` string appears at the top of the rail as a small uppercase label.
 * Items can carry an optional `icon` name for the icon column.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * components/primitives, react-router-dom.
 */
export function SettingsSideNav({
  groups,
  eyebrow,
  className,
}: SettingsSideNavProps): React.ReactElement {
  // `NavLink isActive` compares pathnames only, so every Configuration
  // anchor link (`/settings#paperless`, `/settings#llm`, …) would resolve
  // active simultaneously on the `/settings` page. For anchor links we
  // therefore compare against the live URL hash; pure routed links keep
  // NavLink's built-in matching.
  const location = useLocation();

  return (
    <nav className={cn(styles['nav'], className)} aria-label="Settings">
      {eyebrow !== undefined && (
        <span className={styles['eyebrow']}>{eyebrow}</span>
      )}
      {groups.map((group, groupIndex) => (
        <div
          key={group.title}
          className={cn(
            styles['group'],
            groupIndex < groups.length - 1 && styles['group-bordered'],
          )}
        >
          <span className={styles['group-title']}>{group.title}</span>
          {group.items.map((item) => {
            const hashIndex = item.to.indexOf('#');
            const isAnchor = hashIndex >= 0;
            const anchor = isAnchor ? item.to.slice(hashIndex) : '';
            const targetPath = isAnchor ? item.to.slice(0, hashIndex) : item.to;

            if (isAnchor) {
              // The first anchor in the group is treated as active when the
              // page is loaded without any fragment, so the user always sees
              // a highlighted section.
              const firstAnchorId = group.items.find(
                (i) => i.to.startsWith(targetPath + '#'),
              )?.id;
              const isOnTargetPath = location.pathname === targetPath;
              const isActive =
                isOnTargetPath &&
                (location.hash === anchor ||
                  (location.hash === '' && firstAnchorId === item.id));
              return (
                <a
                  key={item.id}
                  href={item.to}
                  className={cn(
                    styles['link'],
                    isActive && styles['link-active'],
                  )}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {item.icon !== undefined && (
                    <Icon
                      name={item.icon}
                      size="small"
                      className={cn(
                        styles['link-icon'],
                        isActive && styles['link-icon-active'],
                      )}
                    />
                  )}
                  {item.label}
                </a>
              );
            }

            return (
              <NavLink
                key={item.id}
                to={item.to}
                className={({ isActive }) =>
                  cn(styles['link'], isActive && styles['link-active'])
                }
                end
              >
                {({ isActive }) => (
                  <>
                    {item.icon !== undefined && (
                      <Icon
                        name={item.icon}
                        size="small"
                        className={cn(
                          styles['link-icon'],
                          isActive && styles['link-icon-active'],
                        )}
                      />
                    )}
                    {item.label}
                  </>
                )}
              </NavLink>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
