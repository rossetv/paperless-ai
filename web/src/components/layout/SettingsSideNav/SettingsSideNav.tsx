import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { Icon } from '../../primitives/Icon/Icon';
import type { IconName } from '../../primitives/Icon/Icon';
import styles from './SettingsSideNav.module.css';

/** A single navigable item in a {@link SettingsNavGroup}. */
export interface SettingsNavItem {
  /** Used for React keys, never displayed. */
  id: string;
  label: string;
  to: string;
  /** Optional icon shown to the left of the label. */
  icon?: IconName;
}

/** A titled group of settings nav items. */
export interface SettingsNavGroup {
  /** Uppercase group heading. */
  title: string;
  items: SettingsNavItem[];
}

export interface SettingsSideNavProps {
  /** The groups to render, top-to-bottom. */
  groups: SettingsNavGroup[];
  /** Optional eyebrow text above the first group, e.g. "SETTINGS". */
  eyebrow?: string;
  className?: string;
}

/** Read --height-settings-sticky from CSS custom properties; fall back to 140. */
function readStickyOffset(): number {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue('--height-settings-sticky')
    .trim();
  const parsed = parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : 140;
}

/**
 * Scroll-spy over the in-page anchor blocks: returns the id of the block whose
 * top has just passed the sticky-offset line (--height-settings-sticky), or
 * `null` when the page has none of the anchors (e.g. routed /settings/users).
 */
function useAnchorScrollSpy(anchorIds: readonly string[]): string | null {
  const [active, setActive] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (anchorIds.length === 0) {
      setActive(null);
      return undefined;
    }

    // Read the token once per effect run, not per scroll event.
    const stickyOffset = readStickyOffset();

    const findActive = (): void => {
      // Pick the last block whose top has crossed the sticky-offset line,
      // so the active item matches what the user is actually reading.
      const pos = window.scrollY + stickyOffset;
      let current: string | null = null;
      for (const id of anchorIds) {
        const el = document.getElementById(id);
        if (el !== null && el.offsetTop <= pos) {
          current = id;
        }
      }
      // Snap to the last anchor when the page is scrolled to the bottom —
      // the final block may be too short to ever cross the sticky-offset threshold.
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

/** Shared icon + label content for both anchor and NavLink items. */
function NavItemContent({
  icon,
  label,
  isActive,
}: {
  icon: IconName | undefined;
  label: string;
  isActive: boolean;
}): React.ReactElement {
  return (
    <>
      {icon !== undefined && (
        <Icon
          name={icon}
          size="small"
          className={cn(styles['link-icon'], isActive && styles['link-icon-active'])}
        />
      )}
      {label}
    </>
  );
}

/**
 * Left navigation rail of the settings and access-control area.
 *
 * Items are `NavLink`s for routed pages or plain `<a>`s for in-page anchors.
 * Anchor items follow a scroll-spy and scroll smoothly to their section,
 * offset by the sticky header.
 */
export function SettingsSideNav({
  groups,
  eyebrow,
  className,
}: SettingsSideNavProps): React.ReactElement {
  const location = useLocation();

  // useMemo keeps the array identity stable so the scroll-spy effect does not
  // re-run on every render.
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

  /** Scroll the target section into view, offset by the sticky header height. */
  const handleAnchorClick = React.useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, anchorId: string): void => {
      const el = document.getElementById(anchorId);
      if (el === null) return;
      e.preventDefault();
      const stickyOffset = readStickyOffset();
      const top = el.getBoundingClientRect().top + window.scrollY - stickyOffset;
      window.scrollTo({ top, behavior: 'smooth' });
    },
    [],
  );

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
              // Scroll-spy is the single source of truth for active state when
              // the user has scrolled (scrolledActiveId !== null). Falls back to
              // the URL hash when the spy hasn't fired yet (e.g. initial render,
              // JSDOM in tests) so exactly one item is active at all times.
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
                  className={cn(styles['link'], isActive && styles['link-active'])}
                  aria-current={isActive ? 'page' : undefined}
                  onClick={(e) => {
                    handleAnchorClick(e, anchorId);
                  }}
                >
                  <NavItemContent
                    icon={item.icon}
                    label={item.label}
                    isActive={isActive}
                  />
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
                  <NavItemContent
                    icon={item.icon}
                    label={item.label}
                    isActive={isActive}
                  />
                )}
              </NavLink>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
