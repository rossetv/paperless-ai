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
 * Watch the in-page anchor blocks (the ids on the right of every Configuration
 * link's `#…`) and report the one currently in view as the user scrolls.
 *
 * Mirrors mediaman's rail scroll-spy: we pick the block whose top has just
 * passed an offset from the viewport top, so the active item flips as the
 * user reaches each section heading. Falls back to `null` when no anchor
 * blocks are present on the page (e.g. /settings/users routed pages).
 */
function useAnchorScrollSpy(anchorIds: readonly string[]): string | null {
  const [active, setActive] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (anchorIds.length === 0) {
      setActive(null);
      return undefined;
    }

    const findActive = (): void => {
      // Mirror mediaman: y + ~140px finds the block whose heading has
      // crossed the top of the viewport. Walking the list in document
      // order lets the last-matched block win.
      const pos = window.scrollY + 140;
      let current: string | null = null;
      for (const id of anchorIds) {
        const el = document.getElementById(id);
        if (el !== null && el.offsetTop <= pos) {
          current = id;
        }
      }
      // Snap to the last anchor when the page is scrolled to the bottom —
      // the final block may be too short to ever cross the 140px threshold.
      const atBottom =
        window.innerHeight + window.scrollY >= document.body.scrollHeight - 4;
      if (atBottom) {
        const lastVisible = [...anchorIds]
          .reverse()
          .find((id) => document.getElementById(id) !== null);
        if (lastVisible !== undefined) current = lastVisible;
      }
      setActive(current);
    };

    findActive();
    window.addEventListener('scroll', findActive, { passive: true });
    window.addEventListener('resize', findActive);
    return () => {
      window.removeEventListener('scroll', findActive);
      window.removeEventListener('resize', findActive);
    };
  }, [anchorIds]);

  return active;
}

/**
 * The left navigation rail of the settings / access-control area.
 *
 * Fully data-driven: it renders whatever `groups` it is given. Each item is
 * a `NavLink` (routed pages) or a plain `<a>` (in-page anchors). An optional
 * `eyebrow` string appears at the top of the rail as a small uppercase label.
 * Items can carry an optional `icon` name for the icon column.
 *
 * Anchor items participate in a scroll-spy: as the user scrolls the
 * /settings page, the rail flips its active state to mirror whichever block
 * heading has crossed the top of the viewport.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * components/primitives, react-router-dom.
 */
export function SettingsSideNav({
  groups,
  eyebrow,
  className,
}: SettingsSideNavProps): React.ReactElement {
  const location = useLocation();

  // The anchor ids the page exposes — derived from every item.to with a `#`.
  // Stable across renders by serialising; useMemo keeps the array identity
  // steady so the scroll-spy effect does not re-run on every render.
  const anchorIds = React.useMemo(() => {
    const ids: string[] = [];
    for (const group of groups) {
      for (const item of group.items) {
        const hashIdx = item.to.indexOf('#');
        if (hashIdx >= 0) {
          ids.push(item.to.slice(hashIdx + 1));
        }
      }
    }
    return ids;
  }, [groups]);

  const scrolledActiveId = useAnchorScrollSpy(anchorIds);

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
            const anchorId = isAnchor ? item.to.slice(hashIndex + 1) : '';
            const targetPath = isAnchor ? item.to.slice(0, hashIndex) : item.to;

            if (isAnchor) {
              const isOnTargetPath = location.pathname === targetPath;
              // Scroll-spy takes precedence over the URL hash so the active
              // state mirrors what the user is actually looking at, not what
              // they last clicked.
              const isActive =
                isOnTargetPath &&
                (scrolledActiveId !== null
                  ? scrolledActiveId === anchorId
                  : location.hash === anchor ||
                    (location.hash === '' &&
                      anchorIds[0] !== undefined &&
                      anchorIds[0] === anchorId));
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
