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
 * The user enters their SEARCH_API_KEY once; it is POSTed to /api/auth/login
 * and discarded immediately — the key is NEVER stored in JS-accessible memory
 * beyond the controlled input field, which is cleared on submit.
 *
 * On success: the server sets an HttpOnly session cookie and `onSuccess` is
 * called so the parent can route to the search page.
 * On failure: the mutation error is surfaced as an accessible alert; the field
 * is cleared so the user can try again without accidentally re-sending their
 * key via autofill.
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
    const keyToSubmit = apiKey;
    // Clear the field immediately — the key must not persist in the DOM
    // beyond the moment of submission (spec §7.3 security invariant).
    setApiKey('');
    mutation.mutate(
      { api_key: keyToSubmit },
      {
        onSuccess: () => {
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
