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

/** The navigation links, shared by the desktop bar and the mobile tab bar. */
const NAV_LINKS: ReadonlyArray<{
  to: string;
  label: string;
  /** Icon for the mobile bottom tab bar. */
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
 * The authenticated app navigation: `NavBar` on desktop, `MobileTopBar` plus
 * `BottomTabBar` on mobile. Both are always in the DOM; CSS swaps them at the
 * 700px breakpoint. Renders nothing without a signed-in user.
 */
export function AppNavBar(): React.ReactElement | null {
  const { user, role } = useAuth();
  const logout = useLogout();
  const navigate = useNavigate();

  const handleSignOut = React.useCallback(async (): Promise<void> => {
    try {
      await logout.mutateAsync();
    } finally {
      // Go to /login even on failure: a failed logout still clears the cached
      // `me` query, and the bootstrap gate re-resolves auth.
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
        // Spread only when defined, for exactOptionalPropertyTypes.
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
