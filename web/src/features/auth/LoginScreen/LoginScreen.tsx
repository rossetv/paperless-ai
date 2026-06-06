import React from 'react';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { IconButton } from '../../../components/primitives/IconButton/IconButton';
import { useLogin } from '../../../api/hooks';
import { Unauthenticated, ApiError } from '../../../api/client';
import { validateUsername, validatePassword } from '../credentials';
import styles from './LoginScreen.module.css';

/**
 * Map a login error to user-friendly copy.
 *
 * 401 → wrong credentials; 403 → suspended account; anything else → generic.
 * The raw Error.message is never shown — it is internal (e.g. "API error 403").
 */
function loginErrorMessage(e: Error): string {
  if (e instanceof Unauthenticated) return 'Incorrect username or password.';
  if (e instanceof ApiError && e.status === 403) return 'This account is suspended.';
  return 'Sign-in failed. Please try again.';
}

/**
 * The dark "island" sign-in screen.
 *
 * A two-column layout on desktop — brand + hero copy on the left, the sign-in
 * card on the right — collapsing to a centred single column on tablet and
 * mobile. Dark-surfaced in BOTH themes (it uses the forced-dark tokens).
 * Username / password are validated on submit with the shared `credentials`
 * rules; the `useLogin` mutation sets the session cookie.
 *
 * Tier: features/auth (CODE_GUIDELINES §12.3) — composes primitives + api.
 */
export function LoginScreen(): React.ReactElement {
  const [username, setUsername] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [remember, setRemember] = React.useState(false);
  const [showPassword, setShowPassword] = React.useState(false);
  const [usernameError, setUsernameError] = React.useState<string | undefined>(undefined);
  const [passwordError, setPasswordError] = React.useState<string | undefined>(undefined);

  const login = useLogin();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const uErr = validateUsername(username);
    const pErr = validatePassword(password);
    setUsernameError(uErr);
    setPasswordError(pErr);
    if (uErr !== undefined || pErr !== undefined) {
      return;
    }
    // The second argument is an options object for per-call callbacks;
    // mutation-level handlers live in useLogin itself.
    login.mutate({ username, password, remember }, {});
  }

  const errorMessage =
    login.isError && login.error !== null ? loginErrorMessage(login.error) : null;

  return (
    <div className={styles['screen']}>
      <div className={styles['aurora']} aria-hidden="true" />
      <div className={styles['aurora-far']} aria-hidden="true" />

      <div className={styles['layout']}>
        {/* Left — brand + hero copy. */}
        <div className={styles['hero']}>
          <div className={styles['brand-row']}>
            <Brand size={28} />
            <span className={styles['wordmark']}>
              Paperless<span className={styles['wordmark-dim']}>AI</span>
            </span>
          </div>
          <h1 className={styles['headline']}>
            <span>Search every page</span>
            <br />
            <span className={styles['headline-dim']}>you&apos;ve ever filed.</span>
          </h1>
          <p className={styles['subhead']}>
            It read every page. So you don&apos;t have to.
          </p>
        </div>

        {/* Right — the sign-in card. */}
        <div className={styles['card-column']}>
          <div className={styles['card']}>
            <h2 className={styles['card-title']}>Sign in</h2>
            <p className={styles['card-subtitle']}>Use your Paperless AI account.</p>

            <form onSubmit={handleSubmit} noValidate className={styles['form']}>
              <Input
                id="login-username"
                label="Username"
                name="username"
                surface="dark"
                value={username}
                autoComplete="username"
                disabled={login.isPending}
                error={usernameError}
                onChange={(e) => setUsername(e.target.value)}
              />

              <div className={styles['password-field']}>
                <label htmlFor="login-password" className={styles['password-label']}>
                  Password
                </label>
                <div className={styles['password-wrap']}>
                  <Input
                    id="login-password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    surface="dark"
                    value={password}
                    autoComplete="current-password"
                    disabled={login.isPending}
                    error={passwordError}
                    onChange={(e) => setPassword(e.target.value)}
                    className={styles['password-input'] ?? ''}
                  />
                  <IconButton
                    label={showPassword ? 'Hide password' : 'Show password'}
                    onClick={() => setShowPassword((prev) => !prev)}
                    className={styles['show-toggle'] ?? ''}
                  >
                    <Icon name={showPassword ? 'eye-off' : 'eye'} size="small" />
                  </IconButton>
                </div>
              </div>

              <label className={styles['remember']}>
                <input
                  type="checkbox"
                  className={styles['checkbox']}
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                <span className={styles['remember-label']}>
                  Keep me signed in for 7 days
                </span>
              </label>

              {errorMessage !== null && (
                <div className={styles['error']} role="alert">
                  {errorMessage}
                </div>
              )}

              <Button
                type="submit"
                variant="primary"
                disabled={login.isPending}
                className={styles['submit-button'] ?? ''}
              >
                {login.isPending ? 'Signing in…' : 'Sign in'}
              </Button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
