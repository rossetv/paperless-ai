import React from 'react';
import { SettingsLayout } from '../../../components/layout/SettingsLayout/SettingsLayout';
import { Table } from '../../../components/primitives/Table/Table';
import type { Column } from '../../../components/primitives/Table/Table';
import { Avatar } from '../../../components/primitives/Avatar/Avatar';
import { Button } from '../../../components/primitives/Button/Button';
import { RoleBadge } from '../../../components/primitives/RoleBadge/RoleBadge';
import { StatusBadge } from '../../../components/primitives/StatusBadge/StatusBadge';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { useUsers } from '../../../api/hooks';
import { useAuth } from '../../../hooks/useAuth';
import type { User } from '../../../api/types';
import { StatTile } from '../../../components/primitives/StatTile/StatTile';
import { UserEditDrawer } from '../UserEditDrawer/UserEditDrawer';
import { formatShortDate } from '../../../lib/formatDate';
import { deriveInitials } from '../../../lib/deriveInitials';
import styles from './UsersScreen.module.css';

/**
 * A fixed avatar palette — a deterministic colour per user id.
 *
 * References the --colour-avatar-N tokens from tokens.css so there is one
 * source of truth for these values (§12.4 — no hardcoded design values).
 */
const AVATAR_PALETTE = [
  'var(--colour-avatar-0)',
  'var(--colour-avatar-1)',
  'var(--colour-avatar-2)',
  'var(--colour-avatar-3)',
  'var(--colour-avatar-4)',
  'var(--colour-avatar-5)',
] as const;

/** Pick a stable avatar colour for a user by id. */
function avatarColour(id: number): string {
  // Modulo guarantees the index is in bounds; the fallback satisfies TypeScript.
  return AVATAR_PALETTE[id % AVATAR_PALETTE.length] ?? AVATAR_PALETTE[0];
}

/**
 * The user-management screen.
 *
 * Lists every account in a {@link Table}, with a stat row, a header search
 * box, and a {@link UserEditDrawer} for create / edit. Admin-gated by the
 * route guard — this component assumes the caller is an admin and renders
 * the current user (`useAuth`) with a "You" tag and disabled self-actions.
 *
 * Tier: features/access (CODE_GUIDELINES §12.3). Allowed deps: components/*,
 * api/, hooks/, lib/.
 */
export function UsersScreen(): React.ReactElement {
  const usersQuery = useUsers();
  const { user: me } = useAuth();
  const [query, setQuery] = React.useState('');
  // `undefined` = drawer closed; `null` = create mode; a User = edit mode.
  const [drawerUser, setDrawerUser] = React.useState<User | null | undefined>(
    undefined,
  );

  const users = usersQuery.data?.users ?? [];

  // Stat counts.
  const total = users.length;
  const active = users.filter((u) => u.status === 'active').length;
  const admins = users.filter((u) => u.role === 'admin').length;
  const suspended = users.filter((u) => u.status === 'suspended').length;

  // Search filter — case-insensitive over name, username, email.
  const needle = query.trim().toLowerCase();
  const filtered =
    needle.length === 0
      ? users
      : users.filter((u) =>
          [u.display_name ?? '', u.username, u.email ?? '']
            .join(' ')
            .toLowerCase()
            .includes(needle),
        );

  const columns: Column<User>[] = [
    {
      key: 'user',
      header: 'User',
      render: (u) => (
        <div className={styles['identity']}>
          <Avatar initials={deriveInitials(u.display_name ?? null, u.username)} colour={avatarColour(u.id)} />
          <div className={styles['identity-text']}>
            <div className={styles['name-row']}>
              <span className={styles['name']}>
                {u.display_name ?? u.username}
              </span>
              {me?.id === u.id && <span className={styles['tag']}>You</span>}
              {u.status === 'suspended' && (
                <StatusBadge tone="danger">Suspended</StatusBadge>
              )}
            </div>
            <div className={styles['username']}>{u.username}</div>
          </div>
        </div>
      ),
    },
    { key: 'email', header: 'Email', render: (u) => u.email ?? '—' },
    { key: 'role', header: 'Role', width: 'var(--width-col-badge)', render: (u) => <RoleBadge role={u.role} /> },
    {
      key: 'last',
      header: 'Last sign-in',
      width: 'var(--width-col-date-wide)',
      render: (u) => formatShortDate(u.last_login_at),
    },
    {
      key: 'actions',
      header: '',
      width: 'var(--width-col-actions-narrow)',
      align: 'end',
      render: (u) => (
        <div className={styles['row-actions']}>
          <Button
            variant="ghost"
            size="small"
            onClick={() => setDrawerUser(u)}
          >
            Edit
          </Button>
        </div>
      ),
    },
  ];

  return (
    <SettingsLayout
      title="Users"
      subtitle="Anyone with a username and password who can sign in to the web UI."
      actions={
        <Button variant="primary" size="small" onClick={() => setDrawerUser(null)}>
          + Add user
        </Button>
      }
    >
      {usersQuery.isLoading ? (
        <Spinner size="large" label="Loading users…" />
      ) : usersQuery.isError ? (
        <div role="alert">
          <EmptyState
            icon="warning"
            message="Could not load users"
            description="Something went wrong fetching the user list. Refresh to try again."
          />
        </div>
      ) : (
        <>
          <div className={styles['stat-row']}>
            <StatTile value={total} label="total accounts" />
            <StatTile value={active} label="active accounts" />
            <StatTile value={admins} label="administrators" />
            <StatTile value={suspended} label="suspended" />
          </div>
          <div className={styles['toolbar']}>
            <div className={styles['search']}>
              <input
                type="search"
                className={styles['search-input']}
                placeholder="Search users…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search users"
              />
            </div>
          </div>
          <Table
            columns={columns}
            rows={filtered}
            getRowKey={(u) => u.id}
            isRowMuted={(u) => u.status === 'suspended'}
            emptyMessage="No users match — adjust the search or add one."
          />
        </>
      )}

      {drawerUser !== undefined && (
        <UserEditDrawer
          user={drawerUser}
          isSelf={drawerUser !== null && drawerUser.id === me?.id}
          onClose={() => setDrawerUser(undefined)}
        />
      )}
    </SettingsLayout>
  );
}
