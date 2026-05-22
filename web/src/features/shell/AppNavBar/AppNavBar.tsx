import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { NavBar } from '../../../components/layout/NavBar/NavBar';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { UserMenu } from '../../../components/patterns/UserMenu/UserMenu';
import { useAuth } from '../../../hooks/useAuth';
import { useLogout } from '../../../api/hooks';
import { deriveInitials } from '../../../lib/deriveInitials';
import styles from './AppNavBar.module.css';

/**
 * The authenticated application navigation bar.
 *
 * Composes the layout `NavBar` with the `Brand` mark + wordmark, the centre
 * nav links, and a `UserMenu` whose "Sign out" runs the `useLogout` mutation
 * and routes to `/login`.
 *
 * Renders nothing when there is no authenticated user — the protected routes
 * never mount it without a user, but this keeps it safe to drop anywhere.
 *
 * Wave 1 ships only the "Search" link; later waves add Library / Index /
 * Settings to the `links` slot.
 *
 * Tier: features/shell (CODE_GUIDELINES §12.3) — composes layout, patterns,
 * primitives, api and hooks.
 */
export function AppNavBar(): React.ReactElement | null {
  const { user } = useAuth();
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
        <Link to="/" className={cn(styles['link'], styles['link-active'])}>
          Search
        </Link>
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
