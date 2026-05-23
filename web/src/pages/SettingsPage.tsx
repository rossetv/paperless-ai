/**
 * Settings page — the `/settings` route host.
 *
 * Thin `pages`-tier composition: `Page` shell → `AppNavBar` → `SettingsScreen`.
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
import { SettingsScreen } from '../features/settings/SettingsScreen/SettingsScreen';

/** Full-page configuration view at `/settings`. */
export function SettingsPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <SettingsScreen />
    </Page>
  );
}
