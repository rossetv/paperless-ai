import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FailedDocumentsPanel } from './FailedDocumentsPanel';
import type { FailedDocument } from '../../../api/types';

/**
 * Fixtures mirror `FailedDocumentResponse` in `wire.py` exactly.
 * Fields: document_id, title (string | null), failure_count.
 */
const DOCS: FailedDocument[] = [
  {
    document_id: 8421,
    title: 'Scanned receipt #2891 — illegible',
    failure_count: 3,
  },
  {
    document_id: 7188,
    title: null, // backend sends null when no indexed row exists
    failure_count: 1,
  },
];

describe('FailedDocumentsPanel', () => {
  it('renders the panel heading', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText('Failed documents')).toBeInTheDocument();
  });

  it('renders the failure count', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders a non-null document title', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText('Scanned receipt #2891 — illegible')).toBeInTheDocument();
  });

  it('renders a fallback for a null title', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText('(no title)')).toBeInTheDocument();
  });

  it('renders the failure_count for each document', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText(/failed 3 times/i)).toBeInTheDocument();
    expect(screen.getByText(/failed 1 time$/i)).toBeInTheDocument();
  });

  it('renders the document id as a chip', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.getByText('#8421')).toBeInTheDocument();
  });

  it('calls onOpen with the document id when the Preview button is clicked', async () => {
    const onOpen = vi.fn();
    render(<FailedDocumentsPanel documents={DOCS} onOpen={onOpen} />);
    const previewButtons = screen.getAllByRole('button', { name: /^preview$/i });
    await userEvent.click(previewButtons[0]!);
    expect(onOpen).toHaveBeenCalledWith(8421);
  });

  it('renders an all-clear message when the list is empty', () => {
    render(<FailedDocumentsPanel documents={[]} onOpen={vi.fn()} />);
    expect(screen.getByText(/no failed documents/i)).toBeInTheDocument();
  });

  it('does not render Retry buttons (no retry endpoint exists)', () => {
    render(<FailedDocumentsPanel documents={DOCS} onOpen={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
  });
});
