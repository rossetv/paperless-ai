import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { SourceDocument } from '../../../api/types';
import { DocumentPreviewScreen } from './DocumentPreviewScreen';

const SOURCE: SourceDocument = {
  document_id: 9823,
  title: 'Annual energy statement',
  correspondent: 'Npower Energy',
  document_type: 'Statement',
  created: '2025-01-12',
  snippet: 'Twelve direct debits of **£153.94** were collected.',
  paperless_url: 'https://paperless.example.com/documents/9823/',
  score: 0.92,
};

describe('DocumentPreviewScreen', () => {
  it('renders the document title in the viewer chrome', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
  });

  it('embeds the PDF in an iframe pointed at the proxy endpoint', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    const frame = screen.getByTitle(/annual energy statement/i);
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toMatch(/\/api\/documents\/9823\/pdf$/);
  });

  it('fires onClose when the close control is clicked', async () => {
    const onClose = vi.fn();
    render(<DocumentPreviewScreen source={SOURCE} onClose={onClose} />);
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the document metadata in the sidebar', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
    expect(screen.getByText('Statement')).toBeInTheDocument();
  });

  it('renders the matched-content snippet with its highlight', () => {
    const { container } = render(
      <DocumentPreviewScreen source={SOURCE} onClose={() => {}} />,
    );
    expect(container.querySelectorAll('mark')).toHaveLength(1);
  });

  it('shows the relevance score', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    expect(screen.getByText(/0\.92/)).toBeInTheDocument();
  });

  it('offers a download link to the PDF proxy', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    const link = screen.getByRole('link', { name: /download/i });
    expect(link.getAttribute('href')).toMatch(/\/api\/documents\/9823\/pdf$/);
  });

  it('offers an "Open in Paperless" link', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    expect(
      screen.getByRole('link', { name: /open in paperless/i }),
    ).toHaveAttribute(
      'href',
      'https://paperless.example.com/documents/9823/',
    );
  });

  it('falls back to "Document {id}" when the title is null', () => {
    render(
      <DocumentPreviewScreen
        source={{ ...SOURCE, title: null }}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText('Document 9823')).toBeInTheDocument();
  });
});
