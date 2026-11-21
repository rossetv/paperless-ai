import React from 'react';
import { FirstRunSetupScreen } from '../features/auth/FirstRunSetupScreen/FirstRunSetupScreen';

/** Full-page first-run setup view at `/setup`; the screen owns its own layout. */
export function SetupPage(): React.ReactElement {
  return <FirstRunSetupScreen />;
}
