import React, { useState } from 'react';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { Stack } from '../../../components/layout/Stack/Stack';
import { useLogin } from '../../../api/hooks';

export interface LoginFormProps {
  /**
   * Called once the login mutation succeeds and the server has set the session
   * cookie. The parent is responsible for routing to the search page.
   */
  onSuccess: () => void;
}

/**
 * API-key login form implementing the §7.3 login handshake.
 *
 * The user enters their SEARCH_API_KEY once; it is POSTed to /api/auth/login.
 * The field is cleared only on SUCCESS — not before the mutation resolves.
 * Clearing before the mutation meant a failed login (wrong key / network error)
 * would leave the user with an empty field AND a disabled submit button,
 * forcing them to retype from scratch. On success the parent routes away, so
 * clearing on success also acts as a defence-in-depth cleanup.
 *
 * On success: the server sets an HttpOnly session cookie and `onSuccess` is
 * called so the parent can route to the search page.
 * On failure: the mutation error is surfaced as an accessible alert; the typed
 * value remains so the user can correct a typo and resubmit immediately.
 *
 * Loading state: the submit button is disabled and labelled "Logging in…"
 * while the mutation is in flight.
 *
 * Composed from: Input, Button, Stack.
 * No own CSS module (§12.5 — features layer is composition-only).
 */
export function LoginForm({ onSuccess }: LoginFormProps): React.ReactElement {
  const [apiKey, setApiKey] = useState('');
  const mutation = useLogin();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    mutation.mutate(
      { api_key: apiKey },
      {
        onSuccess: () => {
          // Clear the field on success — the key is no longer needed and the
          // parent will route away. This is defence-in-depth; the route change
          // alone would unmount the component.
          setApiKey('');
          onSuccess();
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <Stack direction="vertical" gap={6}>
        <Input
          id="login-api-key"
          label="API Key"
          type="password"
          name="api_key"
          value={apiKey}
          required
          placeholder="Enter your search API key"
          disabled={mutation.isPending}
          onChange={(e) => setApiKey(e.target.value)}
        />

        {mutation.isError && mutation.error !== null && (
          <span role="alert">
            {mutation.error.message}
          </span>
        )}

        <Button
          type="submit"
          variant="primary"
          disabled={mutation.isPending || apiKey.length === 0}
        >
          {mutation.isPending ? 'Logging in…' : 'Log in'}
        </Button>
      </Stack>
    </form>
  );
}
