import { describe, expect, it } from 'vitest';
import { formatShortDate, formatLongDate, isoDateOnly } from './formatDate';

describe('formatShortDate', () => {
  it('formats a calendar date as a short British date', () => {
    expect(formatShortDate('2023-09-05')).toBe('5 Sep 2023');
  });

  it('formats from the date prefix of a full timestamp without timezone drift', () => {
    expect(formatShortDate('2023-09-05T00:00:00+00:00')).toBe('5 Sep 2023');
    expect(formatShortDate('2024-01-31T23:59:59Z')).toBe('31 Jan 2024');
  });

  it('returns an em dash for null', () => {
    expect(formatShortDate(null)).toBe('—');
  });

  it('returns an em dash for an unparseable value', () => {
    expect(formatShortDate('not-a-date')).toBe('—');
    expect(formatShortDate('')).toBe('—');
  });

  it('returns an em dash for an out-of-range month', () => {
    expect(formatShortDate('2023-13-01')).toBe('—');
  });
});

describe('formatLongDate', () => {
  it('formats a calendar date as a long British date', () => {
    expect(formatLongDate('2023-09-05')).toBe('5 September 2023');
    expect(formatLongDate('2026-05-22T10:00:00Z')).toBe('22 May 2026');
  });

  it('formats the full offset timestamp the API actually returns', () => {
    // The document Date arrives as "YYYY-MM-DDTHH:MM:SS+00:00" — the exact
    // shape the operator saw rendered raw.
    expect(formatLongDate('2026-01-13T00:00:00+00:00')).toBe('13 January 2026');
    expect(formatLongDate('2026-05-22T01:30:00-05:00')).toBe('22 May 2026');
  });

  it('returns an em dash for null or unparseable input', () => {
    expect(formatLongDate(null)).toBe('—');
    expect(formatLongDate('rubbish')).toBe('—');
  });
});

describe('isoDateOnly', () => {
  it('extracts the YYYY-MM-DD prefix from a full offset timestamp', () => {
    expect(isoDateOnly('2026-01-13T00:00:00+00:00')).toBe('2026-01-13');
    expect(isoDateOnly('2026-05-22T01:30:00-05:00')).toBe('2026-05-22');
  });

  it('passes a bare calendar date through unchanged', () => {
    expect(isoDateOnly('2023-09-05')).toBe('2023-09-05');
  });

  it('returns an empty string for null or unparseable input', () => {
    expect(isoDateOnly(null)).toBe('');
    expect(isoDateOnly('rubbish')).toBe('');
    expect(isoDateOnly('2023-13-01')).toBe('');
  });
});
