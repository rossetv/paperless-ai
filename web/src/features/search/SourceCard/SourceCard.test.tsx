import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from './SourceCard';

const makeSource = (overrides: Partial<SourceDocument> = {}): SourceDocument => ({
  document_id: 9823,
  title: 'Annual energy statement',
  correspondent: 'Npower Energy',
  document_type: 'Statement',
  created: '2025-01-12',
  snippet: 'Total charges were **£1,847.32** for the year.',
  paperless_url: 'https://paperless.example.com/documents/9823/',
  score: 0.92,
  relevance_tier: 'strong',
  tags: [],
  ...overrides,
});

describe('SourceCard', () => {
  it('renders the document title', () => {
    render(<SourceCard source={makeSource()} index={1} onPreview={() => {}} />);
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
  });

  it('renders the citation index badge', () => {
    render(<SourceCard source={makeSource()} index={2} onPreview={() => {}} />);
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders the correspondent, type and created meta', () => {
    render(<SourceCard source={makeSource()} index={1} onPreview={() => {}} />);
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
    expect(screen.getByText('Statement')).toBeInTheDocument();
    expect(screen.getByText('12 Jan 2025')).toBeInTheDocument();
  });

  it('highlights the bold run in the snippet', () => {
    const { container } = render(
      <SourceCard source={makeSource()} index={1} onPreview={() => {}} />,
    );
    expect(container.querySelectorAll('mark')).toHaveLength(1);
  });

  it('calls onPreview with the document id when "View" is clicked', async () => {
    const onPreview = vi.fn();
    render(<SourceCard source={makeSource()} index={1} onPreview={onPreview} />);
    await userEvent.click(
      screen.getByRole('button', { name: /^view$/i }),
    );
    expect(onPreview).toHaveBeenCalledWith(9823);
  });

  it('shows the relevance badge', () => {
    render(
      <SourceCard
        source={makeSource({ score: 0.92, relevance_tier: 'strong' })}
        index={1}
        onPreview={() => {}}
      />,
    );
    // RelevanceMeter renders the tier label in place of the raw numeric score
    expect(screen.getByText('Strong match')).toBeInTheDocument();
  });

  it('omits the title block gracefully when title is null', () => {
    render(
      <SourceCard
        source={makeSource({ title: null })}
        index={1}
        onPreview={() => {}}
      />,
    );
    // No crash; the card still renders its meta row.
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
  });
});
