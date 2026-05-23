import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { LibraryScreen } from '../features/library/LibraryScreen/LibraryScreen';

/**
 * The `/library` route page.
 *
 * A thin host: the authenticated `AppNavBar` above the `LibraryScreen`
 * browse view, wrapped in the `Page` layout shell — mirroring `SearchPage`.
 * All behaviour lives in `LibraryScreen`; routing and auth gating live in
 * `routes.tsx`.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features and layout only.
 */
export function LibraryPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <LibraryScreen />
    </Page>
  );
}
