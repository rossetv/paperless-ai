import { render, screen } from '@testing-library/react';
import type { SourceDocument } from '../../../api/types';
import { SourceCard } from './SourceCard';

const fullSource: SourceDocument = {
  document_id: 42,
  title: 'Boiler Warranty Certificate',
  correspondent: 'Vaillant',
  document_type: 'Certificate',
  created: '2021-03-15',
  snippet: 'The boiler model EcoTec Plus 838 was installed on 15 March 2021.',
  paperless_url: 'https://paperless.example.com/documents/42/',
  score: 0.95,
};

describe('SourceCard', () => {
  it('renders the document title', () => {
    render(<SourceCard source={fullSource} index={1} />);
    expect(screen.getByText('Boiler Warranty Certificate')).toBeInTheDocument();
  });

  it('renders the correspondent', () => {
    render(<SourceCard source={fullSource} index={1} />);
    expect(screen.getByText(/Vaillant/)).toBeInTheDocument();
  });

  it('renders the document type', () => {
    render(<SourceCard source={fullSource} index={1} />);
    // getAllByText because "Certificate" also appears inside the title string
    const matches = screen.getAllByText(/Certificate/);
    expect(matches.length).toBeGreaterThan(0);
  });

  it('renders the snippet text', () => {
    render(<SourceCard source={fullSource} index={1} />);
    expect(
      screen.getByText(/The boiler model EcoTec Plus 838 was installed/),
    ).toBeInTheDocument();
  });

  it('renders an "Open in Paperless" link pointing to paperless_url', () => {
    render(<SourceCard source={fullSource} index={1} />);
    const link = screen.getByRole('link', { name: /open in paperless/i });
    expect(link).toHaveAttribute('href', 'https://paperless.example.com/documents/42/');
  });

  it('opens the Paperless link in a new tab', () => {
    render(<SourceCard source={fullSource} index={1} />);
    const link = screen.getByRole('link', { name: /open in paperless/i });
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('sets rel="noopener noreferrer" on the Paperless link', () => {
    render(<SourceCard source={fullSource} index={1} />);
    const link = screen.getByRole('link', { name: /open in paperless/i });
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders the citation index', () => {
    render(<SourceCard source={fullSource} index={3} />);
    expect(screen.getByText('[3]')).toBeInTheDocument();
  });

  it('handles null optional fields without crashing', () => {
    const minimal: SourceDocument = {
      document_id: 1,
      title: null,
      correspondent: null,
      document_type: null,
      created: null,
      snippet: 'Snippet only.',
      paperless_url: 'https://paperless.example.com/documents/1/',
      score: 0.5,
    };
    render(<SourceCard source={minimal} index={1} />);
    expect(screen.getByText('Snippet only.')).toBeInTheDocument();
  });

  it('renders as an article for semantic correctness', () => {
    render(<SourceCard source={fullSource} index={1} />);
    expect(document.querySelector('article')).toBeInTheDocument();
  });
});
