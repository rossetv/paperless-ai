/**
 * Username / password validators mirroring the server-side rules, so the
 * client gives immediate feedback: username 3–64 characters of
 * `A-Z a-z 0-9 . _ -`; password at least 12 characters.
 */

/** The permitted-username character pattern, mirroring the server. */
const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;

/**
 * Validate a username. Returns an error message, or `undefined` when valid.
 */
export function validateUsername(value: string): string | undefined {
  if (value.length < 3 || value.length > 64) {
    return 'Username must be between 3 and 64 characters.';
  }
  if (!USERNAME_PATTERN.test(value)) {
    return 'Username may use only letters, numbers, dots, underscores and hyphens.';
  }
  return undefined;
}

/**
 * Validate a password. Returns an error message, or `undefined` when valid.
 */
export function validatePassword(value: string): string | undefined {
  if (value.length < 12) {
    return 'Password must be at least 12 characters.';
  }
  return undefined;
}
