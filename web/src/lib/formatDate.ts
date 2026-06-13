/**
 * Format an ISO-8601 date (or timestamp) as a short British absolute date.
 *
 * A framework-agnostic leaf helper (`lib/`): pure, no React, no API. The one
 * place absolute document/account dates are formatted — replacing the four
 * divergent per-component implementations that previously disagreed on locale,
 * timezone handling, and null behaviour (CODE_GUIDELINES §1.9).
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3, lib allow: []).
 */

/** Short month names for the British "D Mon YYYY" date format. */
const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;

/** Full month names for the British "D Month YYYY" date format. */
const MONTHS_LONG = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

/**
 * Parse the leading `YYYY-MM-DD` of an ISO string into day/month/year parts.
 *
 * Parsed from the calendar prefix rather than via `new Date()` so the result
 * never drifts with the viewer's timezone — a document dated `2023-09-05`
 * reads as 5 Sep 2023 everywhere, not 4 Sep for users west of UTC.
 *
 * @returns the parts, or `null` when the input is null or unparseable.
 */
function isoDateParts(iso: string | null): { day: number; monthIndex: number; year: string } | null {
  if (iso === null) {
    return null;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (match === null) {
    return null;
  }
  const monthIndex = Number(match[2]) - 1;
  if (monthIndex < 0 || monthIndex > 11) {
    return null;
  }
  return { day: Number(match[3]), monthIndex, year: match[1]! };
}

/**
 * Format an ISO date as a short British date — `5 Sep 2023`.
 *
 * Returns an em dash for a null or unparseable value so callers can render the
 * result directly.
 */
export function formatShortDate(iso: string | null): string {
  const parts = isoDateParts(iso);
  if (parts === null) {
    return '—';
  }
  return `${parts.day} ${MONTHS_SHORT[parts.monthIndex]} ${parts.year}`;
}

/**
 * Format an ISO date as a long British date — `5 September 2023`.
 *
 * Returns an em dash for a null or unparseable value.
 */
export function formatLongDate(iso: string | null): string {
  const parts = isoDateParts(iso);
  if (parts === null) {
    return '—';
  }
  return `${parts.day} ${MONTHS_LONG[parts.monthIndex]} ${parts.year}`;
}

/**
 * Extract the `YYYY-MM-DD` calendar prefix from an ISO date or timestamp.
 *
 * A native `<input type="date">` only accepts a bare `YYYY-MM-DD` value, but the
 * API returns the document date as a full offset timestamp
 * (`2026-01-13T00:00:00+00:00`). This strips it back to the date the input — and
 * the resulting PATCH — should carry, without timezone drift (the calendar
 * prefix is taken verbatim, never reinterpreted through `new Date()`).
 *
 * @returns the `YYYY-MM-DD` prefix, or `''` for a null or unparseable value so
 *   callers can pass it straight to an input/`value` prop.
 */
export function isoDateOnly(iso: string | null): string {
  const parts = isoDateParts(iso);
  if (parts === null) {
    return '';
  }
  const month = String(parts.monthIndex + 1).padStart(2, '0');
  const day = String(parts.day).padStart(2, '0');
  return `${parts.year}-${month}-${day}`;
}
