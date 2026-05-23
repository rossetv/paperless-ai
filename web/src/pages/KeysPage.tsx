/**
 * API Keys page — the `/settings/keys` route host.
 *
 * Thin `pages`-tier composition: `Page` shell → `AppNavBar` → `APIKeysScreen`.
 * Admin-gating is enforced by the route guard in `routes.tsx`.
 *
 * `Page` provides the `--colour-bg` background and `100dvh` minimum height,
 * keeping this page consistent with every other authenticated page.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { APIKeysScreen } from '../features/access/APIKeysScreen/APIKeysScreen';

/** Full-page API-key-management view at `/settings/keys`. */
export function KeysPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <APIKeysScreen />
    </Page>
  );
}
