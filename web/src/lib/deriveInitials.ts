/**
 * Derive 1–2 character initials from a display name or username.
 *
 * "Alex Morgan" → "AM"; "alex.morgan" → "AM"; single word → first two
 * letters; empty → "?".
 */
export function deriveInitials(displayName: string | null, username: string): string {
  const source = (displayName ?? username).trim();
  if (source === '') {
    return '?';
  }
  const words = source.split(/[\s._-]+/).filter((w) => w.length > 0);
  if (words.length >= 2) {
    return (words[0]![0]! + words[1]![0]!).toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}
