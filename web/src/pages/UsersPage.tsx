/**
 * Users page — the `/settings/users` route host.
 *
 * Thin `pages`-tier composition: `Page` shell → `AppNavBar` → `UsersScreen`.
 * Admin-gating is enforced one level up by the route guard in `routes.tsx`;
 * this host renders unconditionally.
 *
 * `Page` provides the `--colour-bg` background and `100dvh` minimum height,
 * keeping this page consistent with every other authenticated page.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { UsersScreen } from '../features/access/UsersScreen/UsersScreen';

/** Full-page user-management view at `/settings/users`. */
export function UsersPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <UsersScreen />
    </Page>
  );
}
