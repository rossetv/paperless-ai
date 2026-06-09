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

  it('renders a cost chip when a stage carries a costLabel', () => {
    render(
      <PipelineStages
        stages={[
          {
            label: 'Judging relevance',
            detail: 'per-document verdicts',
            state: 'done',
            costLabel: '1.2k tok · $0.004',
          },
        ]}
      />,
    );
    expect(screen.getByText('1.2k tok · $0.004')).toBeInTheDocument();
  });

  it('omits the cost chip when no costLabel is given', () => {
    render(
      <PipelineStages
        stages={[
          { label: 'Retrieving', detail: 'vector search', state: 'done' },
        ]}
      />,
    );
    expect(screen.queryByText(/tok/)).not.toBeInTheDocument();
  });

  it('prefers a rich detailNode over the plain detail string', () => {
    render(
      <PipelineStages
        stages={[
          {
            label: 'Planning the query',
            detail: 'fallback detail',
            state: 'done',
            detailNode: <span>rewritten: npower bills 2024</span>,
          },
        ]}
      />,
    );
    expect(
      screen.getByText('rewritten: npower bills 2024'),
    ).toBeInTheDocument();
    expect(screen.queryByText('fallback detail')).not.toBeInTheDocument();
  });

  it('renders the judge verdict sublist with kept and dropped docs', () => {
    render(
      <PipelineStages
        stages={[
          {
            label: 'Judging relevance',
            detail: '',
            state: 'done',
            verdicts: [
              {
                docId: 9823,
                title: 'Annual statement',
                keep: true,
                reason: 'matches the tax year',
              },
              {
                docId: 4410,
                title: null,
                keep: false,
                reason: 'different correspondent',
              },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText('Annual statement')).toBeInTheDocument();
    expect(screen.getByText('matches the tax year')).toBeInTheDocument();
    // A null title falls back to the document id.
    expect(screen.getByText('Document 4410')).toBeInTheDocument();
    expect(screen.getByText('different correspondent')).toBeInTheDocument();
    expect(screen.getByText('kept')).toBeInTheDocument();
    expect(screen.getByText('dropped')).toBeInTheDocument();
  });

  it('marks a kept verdict and a dropped verdict distinctly', () => {
    const { container } = render(
      <PipelineStages
        stages={[
          {
            label: 'Judging relevance',
            detail: '',
            state: 'done',
            verdicts: [
              { docId: 1, title: 'A', keep: true, reason: '' },
              { docId: 2, title: 'B', keep: false, reason: '' },
            ],
          },
        ]}
      />,
    );
    expect(container.querySelector('[data-keep="true"]')).toBeInTheDocument();
    expect(container.querySelector('[data-keep="false"]')).toBeInTheDocument();
  });
});
