import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { SettingsScreen } from '../features/settings/SettingsScreen/SettingsScreen';

/** Full-page configuration view at `/settings`; admin-gated in `routes.tsx`. */
export function SettingsPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <SettingsScreen />
    </Page>
  );
}
