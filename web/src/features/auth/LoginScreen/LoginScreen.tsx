import React from 'react';
import { cn } from '../../../lib/cn';
import { Brand } from '../../../components/primitives/Brand/Brand';
import { Input } from '../../../components/primitives/Input/Input';
import { Button } from '../../../components/primitives/Button/Button';
import { useLogin, usePublicStats } from '../../../api/hooks';
import { validateUsername, validatePassword } from '../credentials';
import styles from './LoginScreen.module.css';

/** One splash statistic — value plus caption. */
interface SplashStat {
  value: string;
  label: string;
}

/** Format an integer with thousands separators (e.g. 14238 → "14,238"). */
function formatCount(n: number): string {
  return n.toLocaleString('en-GB');
}

/**
 * The dark "island" sign-in screen.
 *
 * A two-column layout: brand + hero copy + live splash statistics on the
 * left, the sign-in card on the right. Dark-surfaced in BOTH themes (it uses
 * the forced-dark tokens). Username / password are validated on submit with
 * the shared `credentials` rules; the `useLogin` mutation sets the session
 * cookie. The splash statistics come from `usePublicStats` and are omitted
 * entirely if that query fails.
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
  const stats = usePublicStats();

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

  // Build the splash stats only when the query has resolved successfully.
  const splashStats: SplashStat[] | null = stats.isSuccess && stats.data !== undefined
    ? [
        { value: formatCount(stats.data.document_count), label: 'documents indexed' },
        { value: formatCount(stats.data.chunk_count), label: 'semantic chunks' },
      ]
    : null;

  const errorMessage =
    login.isError && login.error !== null ? login.error.message : null;

  return (
    <div className={styles['screen']}>
      <div className={styles['aurora']} aria-hidden="true" />
      <div className={styles['aurora-far']} aria-hidden="true" />

      <div className={styles['layout']}>
        {/* Left — brand + hero + stats */}
        <div className={styles['hero']}>
          <div className={styles['brand-row']}>
            <Brand size={26} color="#fff" />
            <span className={styles['wordmark']}>
              Paperless<span className={styles['wordmark-dim']}>AI</span>
            </span>
          </div>
          <h1 className={styles['headline']}>
            Search every page you&apos;ve ever filed.
          </h1>
          <p className={styles['subhead']}>
            Ask anything. Answers come back with citations — grounded in the
            documents already in your library.
          </p>
          {splashStats !== null && (
            <div className={styles['stats']}>
              {splashStats.map((stat) => (
                <div key={stat.label}>
                  <div className={styles['stat-value']}>{stat.value}</div>
                  <div className={styles['stat-label']}>{stat.label}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right — the sign-in card */}
        <div className={styles['card-column']}>
          <div className={styles['card']}>
            <h2 className={styles['card-title']}>Sign in</h2>
            <p className={styles['card-subtitle']}>Use your Paperless AI account.</p>

            <form onSubmit={handleSubmit} noValidate>
              <div className={styles['field']}>
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
              </div>

              <div className={styles['field']}>
                <div className={styles['password-wrap']}>
                  <Input
                    id="login-password"
                    label="Password"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    surface="dark"
                    value={password}
                    autoComplete="current-password"
                    disabled={login.isPending}
                    error={passwordError}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className={styles['show-toggle']}
                    onClick={() => setShowPassword((prev) => !prev)}
                  >
                    {/* Visually-hidden text gives screen readers and RTL a
                        unique accessible name without conflicting with the
                        Password input's getByLabelText association. */}
                    <span aria-hidden="true">{showPassword ? 'Hide' : 'Show'}</span>
                    <span className="visually-hidden">
                      {showPassword ? 'Hide password' : 'Show password'}
                    </span>
                  </button>
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

              <div className={styles['submit']}>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={login.isPending}
                  className={cn(styles['submit'])}
                >
                  {login.isPending ? 'Signing in…' : 'Sign in'}
                </Button>
              </div>
            </form>

            <p className={styles['note']}>
              Credentials are exchanged for a signed session cookie and never
              leave your network. API keys are for the REST API and MCP server
              only — they cannot sign in here.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
