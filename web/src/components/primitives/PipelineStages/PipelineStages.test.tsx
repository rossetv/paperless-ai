import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import React from 'react';
import { PipelineStages } from './PipelineStages';
import type { PipelineStage } from './PipelineStages';

const stages: PipelineStage[] = [
  { label: 'Planning the query', detail: '3 semantic queries', state: 'done' },
  { label: 'Embedding & retrieving', detail: 'RRF fusion', state: 'active' },
  { label: 'Synthesising the answer', detail: 'Final answer', state: 'pending' },
];

const stageWithBody: PipelineStage = {
  label: 'Planning the query',
  detail: '',
  state: 'done',
  summary: <span>summary marker text</span>,
  body: <span>full body marker text</span>,
};

const stageWithSummaryOnly: PipelineStage = {
  label: 'Retrieving documents',
  detail: 'fallback detail',
  state: 'done',
  summary: <span>retrieval summary</span>,
};

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
        collapsible
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
                score: 0.92,
                paperlessUrl: null,
              },
              {
                docId: 4410,
                title: null,
                keep: false,
                reason: 'different correspondent',
                score: 0.1,
                paperlessUrl: null,
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
    expect(screen.getByText('keep')).toBeInTheDocument();
    expect(screen.getByText('drop')).toBeInTheDocument();
    // The judge's relevance score prefixes each verdict.
    expect(screen.getByText('0.92')).toBeInTheDocument();
    expect(screen.getByText('0.10')).toBeInTheDocument();
  });

  it('marks a kept verdict and a dropped verdict distinctly', () => {
    const { container } = render(
      <PipelineStages
        collapsible
        stages={[
          {
            label: 'Judging relevance',
            detail: '',
            state: 'done',
            verdicts: [
              { docId: 1, title: 'A', keep: true, reason: '', score: 0.9, paperlessUrl: null },
              { docId: 2, title: 'B', keep: false, reason: '', score: 0.2, paperlessUrl: null },
            ],
          },
        ]}
      />,
    );
    expect(container.querySelector('[data-keep="true"]')).toBeInTheDocument();
    expect(container.querySelector('[data-keep="false"]')).toBeInTheDocument();
  });

  it('renders a View control per verdict and fires onPreviewDocument with the doc id', async () => {
    const onPreviewDocument = vi.fn();
    render(
      <PipelineStages
        collapsible
        onPreviewDocument={onPreviewDocument}
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
                reason: 'matches',
                score: 0.9,
                paperlessUrl: 'http://paperless/documents/9823/',
              },
            ],
          },
        ]}
      />,
    );
    const preview = screen.getByRole('button', { name: /view/i });
    await userEvent.click(preview);
    expect(onPreviewDocument).toHaveBeenCalledWith(9823);
  });

  it('omits the View control when no onPreviewDocument handler is given', () => {
    render(
      <PipelineStages
        collapsible
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
                reason: 'matches',
                score: 0.9,
                paperlessUrl: null,
              },
            ],
          },
        ]}
      />,
    );
    expect(
      screen.queryByRole('button', { name: /view/i }),
    ).not.toBeInTheDocument();
  });
});

describe('PipelineStages — collapsible mode', () => {
  it('collapsible=true wraps a stage with a body in a closed <details>', () => {
    render(<PipelineStages collapsible stages={[stageWithBody]} />);
    const details = document.querySelector('details');
    expect(details).not.toBeNull();
    expect((details as HTMLDetailsElement).open).toBe(false);
  });

  it('collapsible=true a stage without a body renders as a plain row (no details)', () => {
    render(<PipelineStages collapsible stages={[stageWithSummaryOnly]} />);
    expect(document.querySelector('details')).toBeNull();
    expect(screen.getByText('retrieval summary')).toBeInTheDocument();
  });

  it('collapsible=false renders the summary only, no body', () => {
    render(<PipelineStages stages={[stageWithBody]} />);
    expect(screen.queryByText('full body marker text')).toBeNull();
    expect(screen.getByText('summary marker text')).toBeInTheDocument();
  });

  it('collapsible=false does not render verdicts', () => {
    const stageWithVerdicts: PipelineStage = {
      label: 'Judging relevance',
      detail: '',
      state: 'done',
      summary: <span>judge summary</span>,
      verdicts: [
        { docId: 1, title: 'Alpha', keep: true, reason: 'yes', score: 0.9, paperlessUrl: null },
      ],
    };
    render(<PipelineStages stages={[stageWithVerdicts]} />);
    expect(screen.queryByText('Alpha')).toBeNull();
    expect(screen.getByText('judge summary')).toBeInTheDocument();
  });

  it('collapsible=true renders verdicts inside the details body', () => {
    const stageWithVerdicts: PipelineStage = {
      label: 'Judging relevance',
      detail: '',
      state: 'done',
      summary: <span>judge summary</span>,
      verdicts: [
        { docId: 1, title: 'Alpha', keep: true, reason: 'yes', score: 0.9, paperlessUrl: null },
      ],
    };
    render(<PipelineStages collapsible stages={[stageWithVerdicts]} />);
    // details wraps the verdict list
    const details = document.querySelector('details');
    expect(details).not.toBeNull();
    // Alpha is rendered inside details body
    expect(screen.getByText('Alpha')).toBeInTheDocument();
  });

  it('renders the verdict action labelled "View" (not "Preview")', async () => {
    const onPreviewDocument = vi.fn();
    render(
      <PipelineStages
        collapsible
        onPreviewDocument={onPreviewDocument}
        stages={[
          {
            label: 'Judging relevance',
            detail: '',
            state: 'done',
            summary: <span>judge summary</span>,
            verdicts: [
              { docId: 9823, title: 'Annual statement', keep: true, reason: 'matches', score: 0.9, paperlessUrl: null },
            ],
          },
        ]}
      />,
    );
    const viewBtn = screen.getByRole('button', { name: /view/i });
    expect(viewBtn).toBeInTheDocument();
    await userEvent.click(viewBtn);
    expect(onPreviewDocument).toHaveBeenCalledWith(9823);
  });

  it('does not render the "Preview" label anywhere (renamed to View)', () => {
    render(
      <PipelineStages
        collapsible
        onPreviewDocument={vi.fn()}
        stages={[
          {
            label: 'Judging relevance',
            detail: '',
            state: 'done',
            summary: <span>judge summary</span>,
            verdicts: [
              { docId: 1, title: 'A', keep: true, reason: '', score: 0.9, paperlessUrl: null },
            ],
          },
        ]}
      />,
    );
    expect(screen.queryByRole('button', { name: /preview/i })).toBeNull();
  });
});
