let segmenter: Intl.Segmenter | null | undefined;

/** Built on first use; null when the browser has no Intl.Segmenter. */
function getSegmenter(): Intl.Segmenter | null {
  if (segmenter === undefined) {
    segmenter =
      typeof Intl.Segmenter === 'function'
        ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
        : null;
  }
  return segmenter;
}

/** The first `count` whole characters of `text`, so an emoji is never cut in half. */
function leadingCharacters(text: string, count: number): string {
  const seg = getSegmenter();
  const pieces = seg
    ? Array.from(seg.segment(text), ({ segment }) => segment)
    : Array.from(text);
  return pieces.slice(0, count).join('');
}

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
    return (leadingCharacters(words[0]!, 1) + leadingCharacters(words[1]!, 1)).toUpperCase();
  }
  return leadingCharacters(source, 2).toUpperCase();
}
