import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { cn } from '../../../lib/cn';
import { NavBar } from '../../../components/layout/NavBar/NavBar';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { UserMenu } from '../../../components/patterns/UserMenu/UserMenu';
import { useAuth } from '../../../hooks/useAuth';
import { useLogout } from '../../../api/hooks';
import styles from './AppNavBar.module.css';

/**
 * Derive 1–2 character initials from a display name or username.
 *
 * "Alex Morgan" → "AM"; "alex.morgan" → "AL"; single word → first two
 * letters; empty → "?".
 */
function deriveInitials(displayName: string | null, username: string): string {
  const source = (displayName ?? username).trim();
  if (source === '') {
    return '?';
  }
  const words = source.split(/[\s._-]+/).filter((w) => w.length > 0);
  if (words.length >= 2) {
    return (words[0]![0]! + words[1]![0]!).toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

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

  if (user === null) {
    return null;
  }

  async function handleSignOut(): Promise<void> {
    try {
      await logout.mutateAsync();
    } finally {
      // Route to /login regardless — a failed logout still clears the cached
      // `me` query, and the bootstrap gate will re-resolve auth.
      navigate('/login', { replace: true });
    }
  }

  const initials = deriveInitials(user.display_name, user.username);

  return (
    <NavBar
      brand={
        <Link to="/" className={styles['brand']}>
          <Brand size={20} color="#fff" />
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
          onSignOut={() => {
            void handleSignOut();
          }}
        />
      }
    />
  );
}
