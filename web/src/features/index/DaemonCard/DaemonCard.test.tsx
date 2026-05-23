import { render, screen } from '@testing-library/react';
import { DaemonCard } from './DaemonCard';
import type { DaemonStatus } from '../../../api/types';

/**
 * Fixture mirrors `DaemonStatusResponse` in `wire.py` exactly.
 * Fields: name, state, detail, processed_count, last_heartbeat.
 */
const RUNNING: DaemonStatus = {
  name: 'ocr',
  state: 'running',
  detail: '3 documents in flight',
  processed_count: 412,
  last_heartbeat: '2026-05-22T09:00:00Z',
};

describe('DaemonCard', () => {
  it('renders the daemon name', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('ocr')).toBeInTheDocument();
  });

  it('renders the detail string', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('3 documents in flight')).toBeInTheDocument();
  });

  it('renders the processed_count figure', () => {
    render(<DaemonCard daemon={RUNNING} />);
    // Formatted as en-GB locale number
    expect(screen.getByText(/412 processed/)).toBeInTheDocument();
  });

  it('renders a relative last-seen time from last_heartbeat', () => {
    render(<DaemonCard daemon={RUNNING} />);
    // last_heartbeat is well in the past relative to test run time
    expect(screen.getByText(/last seen/i)).toBeInTheDocument();
  });

  it('renders a "Running" status label for the running state', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('renders an "Idle" status label for the idle state', () => {
    render(<DaemonCard daemon={{ ...RUNNING, state: 'idle' }} />);
    expect(screen.getByText('Idle')).toBeInTheDocument();
  });

  it('renders a "Stopped" status label for the stopped state', () => {
    render(<DaemonCard daemon={{ ...RUNNING, state: 'stopped' }} />);
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });

  it('renders as an article landmark', () => {
    const { container } = render(<DaemonCard daemon={RUNNING} />);
    expect(container.querySelector('article')).toBeInTheDocument();
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(<DaemonCard daemon={RUNNING} className="extra" />);
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
