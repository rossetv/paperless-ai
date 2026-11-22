import React from 'react';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { Icon } from '../../../components/primitives/Icon/Icon';
import { IconButton } from '../../../components/primitives/IconButton/IconButton';
import { useLogin } from '../../../api/hooks';
import { Unauthenticated, ApiError } from '../../../api/client';
import { validateUsername } from '../../../lib/credentials';
import styles from './LoginScreen.module.css';

/** User-facing copy for a login error; the raw message is internal and never shown. */
function loginErrorMessage(e: Error): string {
  if (e instanceof Unauthenticated) return 'Incorrect username or password.';
  if (e instanceof ApiError && e.status === 403) return 'This account is suspended.';
  if (e instanceof ApiError && e.status === 429) {
    return 'Too many attempts. Wait a while and try again later.';
  }
  return 'Sign-in failed. Please try again.';
}

/**
 * Sign-in screen, dark in both themes: hero copy beside the sign-in card on
 * desktop, one centred column on smaller screens. `useLogin` sets the session
 * cookie.
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
    // Only emptiness: accounts made under an older, shorter minimum must still sign in.
    const pErr = password === '' ? 'Enter your password.' : undefined;
    setUsernameError(uErr);
    setPasswordError(pErr);
    if (uErr !== undefined || pErr !== undefined) {
      // Drop the earlier server error so only the current one shows.
      login.reset();
      return;
    }
    login.mutate({ username, password, remember }, {});
  }

  const errorMessage =
    login.isError && login.error !== null ? loginErrorMessage(login.error) : null;

  return (
    <div className={styles['screen']}>
      <div className={styles['aurora']} aria-hidden="true" />
      <div className={styles['aurora-far']} aria-hidden="true" />

      <div className={styles['layout']}>
        {/* Brand and hero copy */}
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

        {/* Sign-in card */}
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
                  Keep me signed in on this device
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
