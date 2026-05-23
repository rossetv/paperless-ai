/**
 * Index page — the `/index` route host.
 *
 * Thin `pages`-tier composition: `Page` shell → `AppNavBar` → `IndexScreen`.
 * Authentication is enforced one level up by `ProtectedRoute` in `routes.tsx`;
 * this host renders unconditionally. The destructive rebuild-index control
 * inside `IndexScreen` is itself admin-gated.
 *
 * `Page` provides the `--colour-bg` background and `100dvh` minimum height,
 * keeping this page consistent with every other authenticated page.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features + layout only.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IndexScreen } from '../features/index/IndexScreen/IndexScreen';

/** Full-page Index operations dashboard at `/index`. */
export function IndexPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <IndexScreen />
    </Page>
  );
}
