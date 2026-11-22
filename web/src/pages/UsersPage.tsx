import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { UsersScreen } from '../features/access/UsersScreen/UsersScreen';

/** Full-page user-management view at `/settings/users`; admin-gated in `routes.tsx`. */
export function UsersPage(): React.ReactElement {
  return (
    <Page nav={<AppNavBar />}>
      <UsersScreen />
    </Page>
  );
}
