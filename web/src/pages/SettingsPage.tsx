/**
 * Settings page — the `/settings` route host.
 *
 * Thin `pages`-tier composition: the app nav bar above the `SettingsScreen`
 * feature. Admin-gating is enforced one level up by the route guard in
 * `routes.tsx`; this host renders unconditionally.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { SettingsScreen } from '../features/settings/SettingsScreen/SettingsScreen';

/** Full-page configuration view at `/settings`. */
export function SettingsPage(): React.ReactElement {
  return (
    <>
      <AppNavBar />
      <SettingsScreen />
    </>
  );
}
