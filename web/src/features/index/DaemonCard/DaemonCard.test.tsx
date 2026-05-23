import { render, screen } from '@testing-library/react';
import { DaemonCard } from './DaemonCard';
import type { DaemonStatus } from '../../../api/types';

const RUNNING: DaemonStatus = {
  key: 'ocr',
  name: 'OCR',
  role: 'Vision-model transcription of scanned pages',
  state: 'running',
  detail: '3 documents in flight',
  throughput: '412 pages / hr',
};

describe('DaemonCard', () => {
  it('renders the daemon name', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('OCR')).toBeInTheDocument();
  });

  it('renders the role sub-line', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(
      screen.getByText('Vision-model transcription of scanned pages'),
    ).toBeInTheDocument();
  });

  it('renders the detail string', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('3 documents in flight')).toBeInTheDocument();
  });

  it('renders the throughput figure', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('412 pages / hr')).toBeInTheDocument();
  });

  it('renders a "Running" status label for the running state', () => {
    render(<DaemonCard daemon={RUNNING} />);
    expect(screen.getByText('Running')).toBeInTheDocument();
  });

  it('renders an "Idle" status label for the idle state', () => {
    render(
      <DaemonCard daemon={{ ...RUNNING, state: 'idle' }} />,
    );
    expect(screen.getByText('Idle')).toBeInTheDocument();
  });

  it('renders a "Stopped" status label for the stopped state', () => {
    render(
      <DaemonCard daemon={{ ...RUNNING, state: 'stopped' }} />,
    );
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });

  it('renders as an article landmark', () => {
    const { container } = render(<DaemonCard daemon={RUNNING} />);
    expect(container.querySelector('article')).toBeInTheDocument();
  });

  it('forwards a custom className onto the root', () => {
    const { container } = render(
      <DaemonCard daemon={RUNNING} className="extra" />,
    );
    expect(container.firstElementChild?.className).toContain('extra');
  });
});
