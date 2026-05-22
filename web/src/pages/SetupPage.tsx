/**
 * First-run setup page — hosts the `FirstRunSetupScreen` feature.
 *
 * `FirstRunSetupScreen` is a full-bleed dark screen that owns its own
 * layout, the admin-creation form and the `useSetup` mutation. The page adds
 * only the route binding — no chrome, no styling of its own
 * (CODE_GUIDELINES §12.5).
 */

import React from 'react';
import { FirstRunSetupScreen } from '../features/auth/FirstRunSetupScreen/FirstRunSetupScreen';

/** Full-page first-run setup view, mounted at `/setup`. */
export function SetupPage(): React.ReactElement {
  return <FirstRunSetupScreen />;
}
