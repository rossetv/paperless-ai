import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { NavBar } from '../../../components/layout/NavBar/NavBar';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { UserMenu } from '../../../components/patterns/UserMenu/UserMenu';
import { useAuth } from '../../../hooks/useAuth';
import { useLogout } from '../../../api/hooks';
import { deriveInitials } from '../../../lib/deriveInitials';
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
  /** When `true`, the link renders only for `admin` users. */
  adminOnly?: true;
  /** When `true`, matches the route exactly (prevents `/` matching `/library`). */
  end?: true;
}> = [
  { to: '/',        label: 'Search',   end: true },
  { to: '/library', label: 'Library' },
  { to: '/index',   label: 'Index' },
  { to: '/settings', label: 'Settings', adminOnly: true },
] as const;

/**
 * The authenticated application navigation bar.
 *
 * Composes the layout `NavBar` with the `Brand` mark + wordmark, the centre
 * nav links (driven by the `NAV_LINKS` constant — the single authoritative
 * definition of the link set), and a `UserMenu` whose "Sign out" runs the
 * `useLogout` mutation and routes to `/login`.
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

  return (
    <NavBar
      brand={
        <Link to="/" className={styles['brand']}>
          <Brand size={20} />
          <span className={styles['wordmark']}>
            Paperless<span className={styles['wordmark-dim']}>AI</span>
          </span>
        </Link>
      }
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
        <UserMenu
          initials={initials}
          displayName={user.display_name}
          username={user.username}
          email={user.email}
          onSignOut={() => { void handleSignOut(); }}
        />
      }
    />
  );
}
