/**
 * Users page — the `/settings/users` route host.
 *
 * Thin `pages`-tier composition: the app nav bar above the `UsersScreen`
 * feature. Admin-gating is enforced one level up by the route guard in
 * `routes.tsx`; this host renders unconditionally.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { UsersScreen } from '../features/access/UsersScreen/UsersScreen';

/** Full-page user-management view at `/settings/users`. */
export function UsersPage(): React.ReactElement {
  return (
    <>
      <AppNavBar />
      <UsersScreen />
    </>
  );
}
