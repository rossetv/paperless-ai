/**
 * Derive 1–2 character initials from a display name or username.
 *
 * "Alex Morgan" → "AM"; "alex.morgan" → "AM"; single word → first two
 * letters; empty → "?".
 */
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });

/** The first `count` whole characters of `text`, so an emoji is never cut in half. */
function leadingCharacters(text: string, count: number): string {
  let out = '';
  let taken = 0;
  for (const { segment } of segmenter.segment(text)) {
    out += segment;
    taken += 1;
    if (taken === count) {
      break;
    }
  }
  return out;
}

export function deriveInitials(displayName: string | null, username: string): string {
  const source = (displayName ?? username).trim();
  if (source === '') {
    return '?';
  }
  const words = source.split(/[\s._-]+/).filter((w) => w.length > 0);
  if (words.length >= 2) {
    return (leadingCharacters(words[0]!, 1) + leadingCharacters(words[1]!, 1)).toUpperCase();
  }
  return leadingCharacters(source, 2).toUpperCase();
}
