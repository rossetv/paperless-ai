import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { APIKeysScreen } from '../features/access/APIKeysScreen/APIKeysScreen';

/** Full-page API-key-management view at `/settings/keys`; gated in `routes.tsx`. */
export function KeysPage(): React.ReactElement {
  return (
    <Page nav={<AppNavBar />}>
      <APIKeysScreen />
    </Page>
  );
}
