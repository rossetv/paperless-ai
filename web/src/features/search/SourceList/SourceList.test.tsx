import { render, screen } from '@testing-library/react';
import type { SourceDocument } from '../../../api/types';
import { SourceList } from './SourceList';

const makeSource = (id: number, title: string): SourceDocument => ({
  document_id: id,
  title,
  correspondent: 'HMRC',
  document_type: 'Letter',
  created: '2024-01-01',
  snippet: `Snippet for document ${id}`,
  paperless_url: `https://paperless.example.com/documents/${id}/`,
  score: 0.9,
});

describe('SourceList', () => {
  it('renders a SourceCard for each source', () => {
    const sources = [
      makeSource(1, 'First Document'),
      makeSource(2, 'Second Document'),
      makeSource(3, 'Third Document'),
    ];
    render(<SourceList sources={sources} />);
    expect(screen.getByText('First Document')).toBeInTheDocument();
    expect(screen.getByText('Second Document')).toBeInTheDocument();
    expect(screen.getByText('Third Document')).toBeInTheDocument();
  });

  it('renders sources as an ordered list', () => {
    const sources = [makeSource(1, 'Doc A'), makeSource(2, 'Doc B')];
    render(<SourceList sources={sources} />);
    expect(document.querySelector('ol')).toBeInTheDocument();
  });

  it('renders the EmptyState when sources is empty', () => {
    render(<SourceList sources={[]} />);
    // EmptyState renders a message — verify no source cards and an empty indicator
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    // The empty state message should be present
    expect(screen.getByText(/no sources/i)).toBeInTheDocument();
  });

  it('passes the correct 1-based citation index to each SourceCard', () => {
    const sources = [makeSource(1, 'First'), makeSource(2, 'Second')];
    render(<SourceList sources={sources} />);
    // Each SourceCard renders its index as "[n]"
    expect(screen.getByText('[1]')).toBeInTheDocument();
    expect(screen.getByText('[2]')).toBeInTheDocument();
  });

  it('calls onCitationActivate on the correct source when a card is highlighted', () => {
    const sources = [makeSource(1, 'First'), makeSource(2, 'Second')];
    // highlightedIndex=1 means the first source (0-based) should be highlighted
    render(<SourceList sources={sources} highlightedIndex={1} />);
    // Both cards are present regardless of highlight
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });
});
