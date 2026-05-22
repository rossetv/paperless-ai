/**
 * Format an ISO-8601 timestamp as a short human relative time.
 *
 * A framework-agnostic leaf helper (`lib/`): pure, no React, no API. Used by
 * the search idle screen to label recent searches ("2h ago", "yesterday").
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3, lib allow: []).
 */

/** Seconds in each time unit, largest first. */
const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

/**
 * Return a short relative-time label for an ISO-8601 timestamp.
 *
 * Buckets: under a minute → "just now"; under an hour → "Nm ago"; under a
 * day → "Nh ago"; exactly one day → "yesterday"; under a week → "N days
 * ago"; otherwise "N weeks ago". An unparseable input yields an empty
 * string so the caller can simply omit the label.
 *
 * @param iso  The ISO-8601 timestamp to describe.
 * @param now  The reference instant — defaults to the current time;
 *             injectable so tests are deterministic.
 */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) {
    return '';
  }

  const seconds = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));

  if (seconds < MINUTE) {
    return 'just now';
  }
  if (seconds < HOUR) {
    return `${Math.floor(seconds / MINUTE)}m ago`;
  }
  if (seconds < DAY) {
    return `${Math.floor(seconds / HOUR)}h ago`;
  }
  if (seconds < 2 * DAY) {
    return 'yesterday';
  }
  if (seconds < WEEK) {
    return `${Math.floor(seconds / DAY)} days ago`;
  }
  const weeks = Math.floor(seconds / WEEK);
  return `${weeks} ${weeks === 1 ? 'week' : 'weeks'} ago`;
}
