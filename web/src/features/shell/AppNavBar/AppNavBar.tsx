import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { NavBar } from '../../../components/layout/NavBar/NavBar';
import { MobileTopBar } from '../../../components/layout/MobileTopBar/MobileTopBar';
import { BottomTabBar } from '../../../components/layout/BottomTabBar/BottomTabBar';
import type { BottomTabItem } from '../../../components/layout/BottomTabBar/BottomTabBar';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { UserMenu } from '../../../components/patterns/UserMenu/UserMenu';
import { useAuth } from '../../../hooks/useAuth';
import { useLogout } from '../../../api/hooks';
import { deriveInitials } from '../../../lib/deriveInitials';
import { IndexStatusPill } from './IndexStatusPill';
import styles from './AppNavBar.module.css';

/**
 * The canonical navigation link definitions.
 *
 * This is the single authoritative list — add, remove, or rename links here
 * only. The `adminOnly` flag controls visibility: `true` means the link is
 * hidden unless the authenticated user holds the `admin` role.
 *
 * Final set (Wave 7): Search · Library · Index · Settings (admin-only).
 */
const NAV_LINKS: ReadonlyArray<{
  /** React Router `to` path. */
  to: string;
  /** Link label shown in the nav bar. */
  label: string;
  /** Icon name for the mobile bottom tab bar. */
  icon: BottomTabItem['icon'];
  /** When `true`, the link renders only for `admin` users. */
  adminOnly?: true;
  /** When `true`, matches the route exactly (prevents `/` matching `/library`). */
  end?: true;
}> = [
  { to: '/',        label: 'Search',   icon: 'search',   end: true },
  { to: '/library', label: 'Library',  icon: 'library' },
  { to: '/index',   label: 'Index',    icon: 'index' },
  { to: '/settings', label: 'Settings', icon: 'settings', adminOnly: true },
] as const;

/**
 * The authenticated application navigation bar.
 *
 * Composes the layout `NavBar` (desktop) with `MobileTopBar` + `BottomTabBar`
 * (mobile). Both surfaces are always rendered in the DOM; the swap is purely
 * CSS `display: none / flex` at the 700 px breakpoint — no JS-side conditional
 * render — following mediaman's surface-swap pattern.
 *
 * Desktop: `NavBar` with Brand, centre nav links, and `UserMenu` / `IndexStatusPill`.
 * Mobile: `MobileTopBar` carrying Brand + `UserMenu`; `BottomTabBar` with four tabs.
 *
 * The `NAV_LINKS` constant is the single authoritative link definition; icons
 * are declared there so both surfaces stay in sync.
 *
 * Renders nothing when there is no authenticated user — the protected routes
 * never mount it without a user, but this keeps it safe to drop anywhere.
 *
 * Tier: features/shell (CODE_GUIDELINES §12.3) — composes layout, patterns,
 * primitives, api and hooks.
 */
export function AppNavBar(): React.ReactElement | null {
  const { user, role } = useAuth();
  const logout = useLogout();
  const navigate = useNavigate();

  // Stable callback — avoids re-creating on every render and prevents the
  // UserMenu from receiving a new function reference unnecessarily.
  const handleSignOut = React.useCallback(async (): Promise<void> => {
    try {
      await logout.mutateAsync();
    } finally {
      // Route to /login regardless — a failed logout still clears the cached
      // `me` query, and the bootstrap gate will re-resolve auth.
      navigate('/login', { replace: true });
    }
  }, [logout, navigate]);

  if (user === null) {
    return null;
  }

  const initials = deriveInitials(user.display_name, user.username);

  const visibleLinks = NAV_LINKS.filter(
    (link) => link.adminOnly !== true || role === 'admin',
  );

  // ── Shared slots ──────────────────────────────────────────────────────────

  const brandLink = (
    <Link to="/" className={styles['brand']}>
      <Brand size={20} />
      <span className={styles['wordmark']}>
        Paperless<span className={styles['wordmark-dim']}>AI</span>
      </span>
    </Link>
  );

  const userMenuSlot = (
    <UserMenu
      initials={initials}
      displayName={user.display_name}
      username={user.username}
      email={user.email}
      onSignOut={() => { void handleSignOut(); }}
    />
  );

  // ── Desktop NavBar ────────────────────────────────────────────────────────

  const desktopNav = (
    <NavBar
      brand={brandLink}
      links={
        <>
          {visibleLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end === true}
              className={({ isActive }) =>
                cn(styles['link'], isActive && styles['link-active'])
              }
            >
              {link.label}
            </NavLink>
          ))}
        </>
      }
      actions={
        <>
          <IndexStatusPill />
          {userMenuSlot}
        </>
      }
    />
  );

  // ── Mobile surfaces ───────────────────────────────────────────────────────

  const mobileTopBar = (
    <MobileTopBar
      brand={brandLink}
      actions={
        <>
          <IndexStatusPill />
          {userMenuSlot}
        </>
      }
    />
  );

  const mobileTabBar = (
    <BottomTabBar
      items={visibleLinks.map((link) => ({
        to: link.to,
        label: link.label,
        icon: link.icon,
        // NAV_LINKS.end is `true | undefined`; BottomTabItem.end is `boolean | undefined`.
        // Spread only when defined to satisfy exactOptionalPropertyTypes.
        ...(link.end === true ? { end: true as const } : {}),
      }))}
    />
  );

  return (
    <>
      {desktopNav}
      {mobileTopBar}
      {mobileTabBar}
    </>
  );
}
