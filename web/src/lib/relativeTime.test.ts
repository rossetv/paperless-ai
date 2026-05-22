import { relativeTime } from './relativeTime';

/** A fixed "now" so the tests are deterministic. */
const NOW = new Date('2026-05-22T12:00:00Z');

describe('relativeTime', () => {
  it('reports "just now" for the current instant', () => {
    expect(relativeTime('2026-05-22T11:59:30Z', NOW)).toBe('just now');
  });

  it('reports minutes for a sub-hour gap', () => {
    expect(relativeTime('2026-05-22T11:25:00Z', NOW)).toBe('35m ago');
  });

  it('reports hours for a sub-day gap', () => {
    expect(relativeTime('2026-05-22T09:00:00Z', NOW)).toBe('3h ago');
  });

  it('reports "yesterday" for a one-day gap', () => {
    expect(relativeTime('2026-05-21T10:00:00Z', NOW)).toBe('yesterday');
  });

  it('reports days for a multi-day gap', () => {
    expect(relativeTime('2026-05-19T12:00:00Z', NOW)).toBe('3 days ago');
  });

  it('reports weeks for a multi-week gap', () => {
    expect(relativeTime('2026-05-01T12:00:00Z', NOW)).toBe('3 weeks ago');
  });

  it('returns an empty string for an unparseable timestamp', () => {
    expect(relativeTime('not-a-date', NOW)).toBe('');
  });
});
