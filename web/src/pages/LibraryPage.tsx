import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { AppNavBar } from '../features/shell/AppNavBar/AppNavBar';
import { LibraryScreen } from '../features/library/LibraryScreen/LibraryScreen';

/** The `/library` route page: `AppNavBar` above `LibraryScreen`. */
export function LibraryPage(): React.ReactElement {
  return (
    <Page>
      <AppNavBar />
      <LibraryScreen />
    </Page>
  );
}
