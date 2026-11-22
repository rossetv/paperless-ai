import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { IndexScreen } from '../features/index/IndexScreen/IndexScreen';

/**
 * Full-page Index operations dashboard at `/index`. Auth is enforced by
 * `ProtectedRoute`; the rebuild control inside `IndexScreen` is admin-gated.
 */
export function IndexPage(): React.ReactElement {
  return (
    <Page nav={<AppNavBar />}>
      <IndexScreen />
    </Page>
  );
}
