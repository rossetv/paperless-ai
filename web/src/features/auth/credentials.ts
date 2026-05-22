/**
 * Shared username / password validation for the auth screens.
 *
 * Mirrors the server-side rules of the Wave 1 contract so the client gives
 * immediate feedback. Both `LoginScreen` and `FirstRunSetupScreen` import
 * these — the rules live here exactly once.
 *
 * Rules:
 *   - username: 3–64 characters, only `A-Z a-z 0-9 . _ -`
 *   - password: at least 8 characters
 *
 * Allowed deps: none — a leaf helper inside the auth feature folder.
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
  if (value.length < 8) {
    return 'Password must be at least 8 characters.';
  }
  return undefined;
}
