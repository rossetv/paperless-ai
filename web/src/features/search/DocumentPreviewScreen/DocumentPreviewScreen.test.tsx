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
  tags: ['Utilities', 'Energy'],
};

/**
 * Render with a real search context — the default for most tests below.
 * Standalone-mode tests render directly without `searchContext`.
 */
function renderPreview(
  overrides: Partial<SourceDocument> = {},
  opts: { sourceIndex?: number; sourceCount?: number } = {},
) {
  return render(
    <DocumentPreviewScreen
      source={{ ...SOURCE, ...overrides }}
      onClose={() => {}}
      searchContext={{
        sourceIndex: opts.sourceIndex ?? 1,
        sourceCount: opts.sourceCount ?? 4,
      }}
    />,
  );
}

describe('DocumentPreviewScreen', () => {
  it('renders the document title in the viewer chrome', () => {
    renderPreview();
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
  });

  it('embeds the PDF in an iframe pointed at the proxy endpoint', () => {
    renderPreview();
    const frame = screen.getByTitle(/annual energy statement/i);
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toMatch(/\/api\/documents\/9823\/pdf$/);
  });

  it('fires onClose when the close control is clicked', async () => {
    const onClose = vi.fn();
    render(
      <DocumentPreviewScreen
        source={SOURCE}
        onClose={onClose}
        searchContext={{ sourceIndex: 1, sourceCount: 4 }}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('renders the document metadata in the sidebar', () => {
    renderPreview();
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
    expect(screen.getByText('Statement')).toBeInTheDocument();
  });

  it('renders the matched-content snippet with its highlight', () => {
    const { container } = renderPreview();
    expect(container.querySelectorAll('mark')).toHaveLength(1);
  });

  it('shows the relevance score', () => {
    renderPreview();
    expect(screen.getByText(/0\.92/)).toBeInTheDocument();
  });

  it('offers a download link to the PDF proxy', () => {
    renderPreview();
    const link = screen.getByRole('link', { name: /download/i });
    expect(link.getAttribute('href')).toMatch(/\/api\/documents\/9823\/pdf$/);
  });

  it('offers an "Open in Paperless" link', () => {
    renderPreview();
    expect(
      screen.getByRole('link', { name: /open in paperless/i }),
    ).toHaveAttribute(
      'href',
      'https://paperless.example.com/documents/9823/',
    );
  });

  it('falls back to "Document {id}" when the title is null', () => {
    renderPreview({ title: null });
    expect(screen.getByText('Document 9823')).toBeInTheDocument();
  });

  it('shows the citation badge with the correct source index', () => {
    renderPreview({}, { sourceIndex: 2, sourceCount: 5 });
    // CitationMark renders the numeral in an aria-hidden span
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows the "Source N of M" caption', () => {
    renderPreview({}, { sourceIndex: 3, sourceCount: 7 });
    expect(screen.getByText('Source 3 of 7')).toBeInTheDocument();
  });

  it('renders tags as chips when the source has tags', () => {
    renderPreview({ tags: ['Utilities', 'Energy'] });
    expect(screen.getByText('Utilities')).toBeInTheDocument();
    expect(screen.getByText('Energy')).toBeInTheDocument();
    expect(screen.getByText('TAGS')).toBeInTheDocument();
  });

  it('renders no TAGS section when tags is empty', () => {
    renderPreview({ tags: [] });
    expect(screen.queryByText('TAGS')).not.toBeInTheDocument();
  });

  it('renders no TAGS section when tags is absent', () => {
    // Cast to PreviewableDocument (no tags field) to simulate a fabricated source
    // from Library/Index that does not carry the tags property.
    const noTags: Parameters<typeof DocumentPreviewScreen>[0]['source'] = {
      document_id: SOURCE.document_id,
      title: SOURCE.title,
      correspondent: SOURCE.correspondent,
      document_type: SOURCE.document_type,
      created: SOURCE.created,
      snippet: SOURCE.snippet,
      paperless_url: SOURCE.paperless_url,
      score: SOURCE.score,
    };
    render(<DocumentPreviewScreen source={noTags} onClose={() => {}} />);
    expect(screen.queryByText('TAGS')).not.toBeInTheDocument();
  });

  // ── Standalone mode — no search context. ──
  it('omits the "Source N of M" caption when there is no search context', () => {
    render(
      <DocumentPreviewScreen
        source={{ ...SOURCE, snippet: '', score: 0 }}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByText(/Source \d+ of \d+/)).not.toBeInTheDocument();
  });

  it('omits the matched-content panel when there is no search context', () => {
    render(
      <DocumentPreviewScreen
        source={{ ...SOURCE, snippet: '', score: 0 }}
        onClose={() => {}}
      />,
    );
    expect(screen.queryByText(/matched in this document/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/relevance/i)).not.toBeInTheDocument();
  });

  it('still renders title, metadata, and tags in standalone mode', () => {
    render(<DocumentPreviewScreen source={SOURCE} onClose={() => {}} />);
    expect(screen.getByText('Annual energy statement')).toBeInTheDocument();
    expect(screen.getByText('Npower Energy')).toBeInTheDocument();
    expect(screen.getByText('Utilities')).toBeInTheDocument();
  });
});
