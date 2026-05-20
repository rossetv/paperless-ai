/**
 * Login page — composes the `LoginForm` feature inside the page layout.
 *
 * Responsibilities:
 * - Render `Page` + `Container` + `LoginForm`.
 * - Wire `LoginForm`'s `onSuccess` to `useAuth().login()`.
 *
 * Zero styling of its own (CODE_GUIDELINES §12.5): no `.module.css`,
 * no hardcoded design values. Layout and visual treatment come from the
 * `Page`, `Container`, and `Stack` layout components.
 */

import React from 'react';
import { Page } from '../components/layout/Page/Page';
import { Container } from '../components/layout/Container/Container';
import { Stack } from '../components/layout/Stack/Stack';
import { LoginForm } from '../features/auth/LoginForm/LoginForm';
import { useAuth } from '../hooks/useAuth';

/**
 * Full-page login view shown when `useAuth().authenticated` is false.
 *
 * On successful login (`LoginForm.onSuccess`) the auth state is flipped to
 * `authenticated: true`, which causes the router in `App` to swap this page
 * out for `SearchPage`.
 */
export function LoginPage(): React.ReactElement {
  const { login } = useAuth();

  return (
    <Page>
      <Container>
        <Stack direction="vertical" gap={8}>
          <LoginForm onSuccess={login} />
        </Stack>
      </Container>
    </Page>
  );
}
