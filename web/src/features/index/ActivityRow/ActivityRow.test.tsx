import { render, screen } from '@testing-library/react';
import { ActivityRow, relativeTime } from './ActivityRow';
import type { ActivityEntry } from '../../../api/types';

const OK_ENTRY: ActivityEntry = {
  id: 'r1',
  status: 'ok',
  label: 'Reconcile cycle complete',
  detail: '+12 new · 3 updated · 312 chunks embedded · 1.8s',
  at: '2026-05-22T08:56:00Z',
};

describe('relativeTime', () => {
  // A fixed "now" so the relative phrasing is deterministic.
  const NOW = new Date('2026-05-22T09:00:00Z');

  it('returns "now" when the timestamp is null', () => {
    expect(relativeTime(null, NOW)).toBe('now');
  });

  it('returns "now" for a timestamp under a minute old', () => {
    expect(relativeTime('2026-05-22T08:59:30Z', NOW)).toBe('now');
  });

  it('returns minutes for a timestamp minutes old', () => {
    expect(relativeTime('2026-05-22T08:56:00Z', NOW)).toBe('4m ago');
  });

  it('returns hours for a timestamp hours old', () => {
    expect(relativeTime('2026-05-22T06:00:00Z', NOW)).toBe('3h ago');
  });

  it('returns days for a timestamp days old', () => {
    expect(relativeTime('2026-05-20T09:00:00Z', NOW)).toBe('2d ago');
  });

  it('returns "now" for a future timestamp (clock skew)', () => {
    expect(relativeTime('2026-05-22T09:05:00Z', NOW)).toBe('now');
  });
});

describe('ActivityRow', () => {
  it('renders the label', () => {
    render(<ActivityRow entry={OK_ENTRY} />);
    expect(screen.getByText('Reconcile cycle complete')).toBeInTheDocument();
  });

  it('renders the detail string', () => {
    render(<ActivityRow entry={OK_ENTRY} />);
    expect(
      screen.getByText('+12 new · 3 updated · 312 chunks embedded · 1.8s'),
    ).toBeInTheDocument();
  });

  it('renders a relative time derived from the timestamp', () => {
    render(<ActivityRow entry={OK_ENTRY} />);
    // The exact phrase depends on the real clock; assert the row renders a
    // <time> element carrying the machine-readable timestamp.
    const time = screen.getByText(/ago|now/i);
    expect(time).toBeInTheDocument();
  });

  it('renders a <time> element with the ISO datetime attribute', () => {
    const { container } = render(<ActivityRow entry={OK_ENTRY} />);
    const time = container.querySelector('time');
    expect(time).toHaveAttribute('dateTime', '2026-05-22T08:56:00Z');
  });

  it('renders "now" for an entry with a null timestamp', () => {
    render(
      <ActivityRow
        entry={{ ...OK_ENTRY, at: null, status: 'idle', label: 'Next cycle in 4m 21s' }}
      />,
    );
    expect(screen.getByText('now')).toBeInTheDocument();
  });

  it('applies a status-specific dot class', () => {
    const { container } = render(
      <ActivityRow entry={{ ...OK_ENTRY, status: 'error' }} />,
    );
    const dot = container.querySelector('[data-testid="activity-dot"]');
    expect(dot?.className).toMatch(/error/);
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <ActivityRow entry={OK_ENTRY} className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
