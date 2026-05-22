import { render, screen } from '@testing-library/react';
import { PipelineStages } from './PipelineStages';
import type { PipelineStage } from './PipelineStages';

const stages: PipelineStage[] = [
  { label: 'Planning the query', detail: '3 semantic queries', state: 'done' },
  { label: 'Embedding & retrieving', detail: 'RRF fusion', state: 'active' },
  { label: 'Synthesising the answer', detail: 'Final answer', state: 'pending' },
];

describe('PipelineStages', () => {
  it('renders every stage label', () => {
    render(<PipelineStages stages={stages} />);
    expect(screen.getByText('Planning the query')).toBeInTheDocument();
    expect(screen.getByText('Embedding & retrieving')).toBeInTheDocument();
    expect(screen.getByText('Synthesising the answer')).toBeInTheDocument();
  });

  it('renders every stage detail line', () => {
    render(<PipelineStages stages={stages} />);
    expect(screen.getByText('3 semantic queries')).toBeInTheDocument();
    expect(screen.getByText('RRF fusion')).toBeInTheDocument();
  });

  it('marks the done stage with data-state="done"', () => {
    const { container } = render(<PipelineStages stages={stages} />);
    expect(
      container.querySelector('[data-state="done"]'),
    ).toBeInTheDocument();
  });

  it('shows an "in progress" marker on the active stage', () => {
    render(<PipelineStages stages={stages} />);
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it('does not show "in progress" when no stage is active', () => {
    render(
      <PipelineStages
        stages={[
          { label: 'A', detail: 'a', state: 'done' },
          { label: 'B', detail: 'b', state: 'done' },
        ]}
      />,
    );
    expect(screen.queryByText(/in progress/i)).not.toBeInTheDocument();
  });

  it('renders as an ordered list', () => {
    const { container } = render(<PipelineStages stages={stages} />);
    expect(container.querySelector('ol')).toBeInTheDocument();
  });

  it('merges a custom className', () => {
    const { container } = render(
      <PipelineStages stages={stages} className="extra" />,
    );
    expect((container.firstChild as Element).className).toContain('extra');
  });
});
