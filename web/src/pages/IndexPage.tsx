/**
 * Index page — the `/index` route host.
 *
 * Thin `pages`-tier composition: the app nav bar above the `IndexScreen`
 * feature. Authentication is enforced one level up by `ProtectedRoute` in
 * `routes.tsx`; this host renders unconditionally. The destructive
 * rebuild-index control inside `IndexScreen` is itself admin-gated.
 *
 * Tier: pages (CODE_GUIDELINES §12.3) — composes features only.
 */

import React from 'react';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IndexScreen } from '../features/index/IndexScreen/IndexScreen';

/** Full-page Index operations dashboard at `/index`. */
export function IndexPage(): React.ReactElement {
  return (
    <>
      <AppNavBar />
      <IndexScreen />
    </>
  );
}
