/** A single class-name part: a string, or a falsy value to be dropped. */
export type ClassValue = string | false | null | undefined;

/**
 * Join class-name parts into a single space-separated string.
 *
 * Falsy parts (`false`, `null`, `undefined`, `''`) are dropped, so a
 * conditional class can be written inline as `condition && styles.modifier`.
 */
export function cn(...parts: ClassValue[]): string {
  return parts.filter(Boolean).join(' ');
}
