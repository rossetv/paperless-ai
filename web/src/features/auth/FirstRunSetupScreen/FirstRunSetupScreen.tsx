import React from 'react';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { useSetup } from '../../../api/hooks';
import { ApiError } from '../../../api/client';
import { validateUsername, validatePassword } from '../../../lib/credentials';
import styles from './FirstRunSetupScreen.module.css';

/**
 * The dark first-run setup screen.
 *
 * Shown only while no users exist (the bootstrap gate routes here). Collects
 * the setup token printed to the container logs plus the first admin's
 * username, password and a confirmation. Dark-surfaced in BOTH themes via the
 * forced-dark tokens. Username / password rules are the shared `credentials`
 * validators; the confirmation must match.
 *
 * On success the `useSetup` mutation invalidates the setup-status and `me`
 * queries — the bootstrap gate then routes the freshly signed-in admin into
 * the app.
 *
 * Tier: features/auth (CODE_GUIDELINES §12.3) — composes primitives + api.
 */
export function FirstRunSetupScreen(): React.ReactElement {
  const [token, setToken] = React.useState('');
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [confirm, setConfirm] = React.useState('');
  const [tokenError, setTokenError] = React.useState<string | undefined>(undefined);
  const [usernameError, setUsernameError] = React.useState<string | undefined>(undefined);
  const [passwordError, setPasswordError] = React.useState<string | undefined>(undefined);
  const [confirmError, setConfirmError] = React.useState<string | undefined>(undefined);

  const setup = useSetup();

  /**
   * Map a setup error to user-friendly copy.
   *
   * 403 → bad token; 409 → already set up; anything else → generic.
   * The raw Error.message is never shown — it is internal (e.g. "API error 403").
   */
  function setupErrorMessage(e: Error): string {
    if (e instanceof ApiError && e.status === 403) return 'Invalid setup token.';
    if (e instanceof ApiError && e.status === 409) return 'Paperless AI is already set up.';
    return 'Setup failed. Please try again.';
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    const tErr = token.trim().length === 0 ? 'Enter the setup token from the logs.' : undefined;
    const uErr = validateUsername(username);
    const pErr = validatePassword(password);
    const cErr = password !== confirm ? 'Passwords do not match.' : undefined;

    setTokenError(tErr);
    setUsernameError(uErr);
    setPasswordError(pErr);
    setConfirmError(cErr);

    if (tErr !== undefined || uErr !== undefined || pErr !== undefined || cErr !== undefined) {
      return;
    }
    // The second argument is an options object for per-call callbacks;
    // mutation-level handlers live in useSetup itself.
    setup.mutate({ token, username, password }, {});
  }

  const errorMessage =
    setup.isError && setup.error !== null ? setupErrorMessage(setup.error) : null;

  return (
    <div className={styles['screen']}>
      <div className={styles['aurora']} aria-hidden="true" />

      <div className={styles['card']}>
        <div className={styles['brand-row']}>
          <Brand size={26} />
          <span className={styles['wordmark']}>
            Paperless<span className={styles['wordmark-dim']}>AI</span>
          </span>
        </div>

        <h1 className={styles['title']}>Create the first admin</h1>
        <p className={styles['subtitle']}>
          Paperless AI has no accounts yet. Set up the administrator below.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <div className={styles['field']}>
            <Input
              id="setup-token"
              label="Setup token"
              name="token"
              surface="dark"
              value={token}
              autoComplete="off"
              disabled={setup.isPending}
              error={tokenError}
              onChange={(e) => setToken(e.target.value)}
            />
          </div>

          <div className={styles['field']}>
            <Input
              id="setup-username"
              label="Username"
              name="username"
              surface="dark"
              value={username}
              autoComplete="username"
              disabled={setup.isPending}
              error={usernameError}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>

          <div className={styles['field']}>
            <Input
              id="setup-password"
              label="Password"
              name="password"
              type="password"
              surface="dark"
              value={password}
              autoComplete="new-password"
              disabled={setup.isPending}
              error={passwordError}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <div className={styles['field']}>
            <Input
              id="setup-confirm"
              label="Confirm password"
              name="confirm"
              type="password"
              surface="dark"
              value={confirm}
              autoComplete="new-password"
              disabled={setup.isPending}
              error={confirmError}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>

          {errorMessage !== null && (
            <div className={styles['error']} role="alert">
              {errorMessage}
            </div>
          )}

          <div className={styles['submit']}>
            <Button
              type="submit"
              variant="primary"
              disabled={setup.isPending}
              className={styles['submit-button'] ?? ''}
            >
              {setup.isPending ? 'Creating…' : 'Create admin account'}
            </Button>
          </div>
        </form>

        <p className={styles['note']}>
          The setup token was printed to the container logs at startup — look
          for the line beginning &ldquo;SETUP TOKEN&rdquo;.
        </p>
      </div>
    </div>
  );
}
