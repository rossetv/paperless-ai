import { render, screen } from '@testing-library/react';
import { ActivityRow } from './ActivityRow';
import type { ReconcileCycle } from '../../../api/types';

/**
 * Fixture mirrors `ReconcileCycleResponse` in `wire.py` exactly.
 * Fields: id, kind, started_at, finished_at, ok, summary, detail.
 */
const OK_CYCLE: ReconcileCycle = {
  id: 1,
  kind: 'sync',
  started_at: '2026-05-22T08:56:00Z',
  finished_at: '2026-05-22T08:56:02Z',
  ok: true,
  summary: { indexed: 12, failed: 0, skipped: 3 },
  detail: 'incremental sync complete',
};

// Unit tests for relativeTime are in lib/relativeTime.test.ts.

describe('ActivityRow', () => {
  it('renders the cycle kind label', () => {
    render(<ActivityRow cycle={OK_CYCLE} />);
    expect(screen.getByText(/reconcile cycle/i)).toBeInTheDocument();
  });

  it('renders the detail string', () => {
    render(<ActivityRow cycle={OK_CYCLE} />);
    expect(screen.getByText(/incremental sync complete/)).toBeInTheDocument();
  });

  it('renders summary counts in the detail area', () => {
    render(<ActivityRow cycle={OK_CYCLE} />);
    // summary { indexed: 12, failed: 0, skipped: 3 } — zero counts are omitted
    expect(screen.getByText(/12 indexed/)).toBeInTheDocument();
    expect(screen.getByText(/3 skipped/)).toBeInTheDocument();
  });

  it('renders a <time> element with the ISO datetime attribute', () => {
    const { container } = render(<ActivityRow cycle={OK_CYCLE} />);
    const time = container.querySelector('time');
    expect(time).toHaveAttribute('dateTime', '2026-05-22T08:56:00Z');
  });

  it('applies an ok dot class for a successful cycle', () => {
    const { container } = render(<ActivityRow cycle={OK_CYCLE} />);
    const dot = container.querySelector('[data-testid="activity-dot"]');
    expect(dot?.className).toMatch(/ok/);
  });

  it('applies an error dot class for a failed cycle', () => {
    const { container } = render(
      <ActivityRow cycle={{ ...OK_CYCLE, ok: false }} />,
    );
    const dot = container.querySelector('[data-testid="activity-dot"]');
    expect(dot?.className).toMatch(/error/);
  });

  it('renders "sweep" kind as "Deletion sweep"', () => {
    render(<ActivityRow cycle={{ ...OK_CYCLE, kind: 'sweep' }} />);
    expect(screen.getByText(/deletion sweep/i)).toBeInTheDocument();
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <ActivityRow cycle={OK_CYCLE} className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
