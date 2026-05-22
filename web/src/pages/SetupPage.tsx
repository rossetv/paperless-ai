/**
 * First-run setup page — hosts the `FirstRunSetupScreen` feature.
 *
 * Placeholder body for now; the real `FirstRunSetupScreen` is wired in a
 * later task. Zero styling of its own (CODE_GUIDELINES §12.5).
 */

import React from 'react';

/** Full-page first-run setup view, shown at `/setup` when no users exist. */
export function SetupPage(): React.ReactElement {
  return <div data-testid="setup-page">Setup</div>;
}
