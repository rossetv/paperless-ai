/**
 * Login page — hosts the `LoginScreen` feature.
 *
 * `LoginScreen` is a full-bleed dark screen that owns its own layout, the
 * sign-in form, validation and the `useLogin` mutation. The page therefore
 * adds nothing but the route binding — no `Page`/`Container` chrome, no
 * styling of its own (CODE_GUIDELINES §12.5).
 */

import React from 'react';
import { LoginScreen } from '../features/auth/LoginScreen/LoginScreen';

/** Full-page sign-in view, mounted at `/login`. */
export function LoginPage(): React.ReactElement {
  return <LoginScreen />;
}
