/**
 * Class-name join helper.
 *
 * Every component composes a CSS-Modules class list from a base class, some
 * conditional modifier classes, and an optional caller-supplied `className`.
 * The conditional and optional parts are frequently `false`, `null`, or
 * `undefined`. `cn` filters those out and joins the survivors with a single
 * space — so a component writes `cn(styles.base, active && styles.active,
 * className)` instead of hand-rolling a filter-and-join over an array literal.
 *
 * Allowed deps: none. `lib/` is a leaf layer (CODE_GUIDELINES §12.3) — every
 * layer may import it; it imports nothing.
 */

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
