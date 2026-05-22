/**
 * API Keys page — the `/settings/keys` route host.
 *
 * Thin `pages`-tier composition: the app nav bar above the `APIKeysScreen`
 * feature. Admin-gating is enforced by the route guard in `routes.tsx`.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { APIKeysScreen } from '../features/access/APIKeysScreen/APIKeysScreen';

/** Full-page API-key-management view at `/settings/keys`. */
export function KeysPage(): React.ReactElement {
  return (
    <>
      <AppNavBar />
      <APIKeysScreen />
    </>
  );
}
