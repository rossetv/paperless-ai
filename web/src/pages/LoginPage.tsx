import React from 'react';
import { LoginScreen } from '../features/auth/LoginScreen/LoginScreen';

/** Full-page sign-in view at `/login`; `LoginScreen` owns its own full-bleed layout. */
export function LoginPage(): React.ReactElement {
  return <LoginScreen />;
}
