import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FailedDocumentsPanel } from './FailedDocumentsPanel';
import type { FailedDocument } from '../../../api/types';

const DOCS: FailedDocument[] = [
  {
    document_id: 8421,
    title: 'Scanned receipt #2891 — illegible',
    reason: 'OCR refused on all 3 model fallback attempts',
    failed_at: '2026-05-22T08:48:00Z',
  },
  {
    document_id: 7188,
    title: 'Encrypted PDF · password protected',
    reason: 'Page conversion failed: PDF requires password',
    failed_at: '2026-05-22T07:00:00Z',
  },
];

describe('FailedDocumentsPanel', () => {
  it('renders the panel heading', () => {
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('Failed documents')).toBeInTheDocument();
  });

  it('renders the failure count', () => {
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders each document title', () => {
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('Scanned receipt #2891 — illegible')).toBeInTheDocument();
    expect(screen.getByText('Encrypted PDF · password protected')).toBeInTheDocument();
  });

  it('renders each failure reason', () => {
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(
      screen.getByText('OCR refused on all 3 model fallback attempts'),
    ).toBeInTheDocument();
  });

  it('renders the document id as a chip', () => {
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(screen.getByText('#8421')).toBeInTheDocument();
  });

  it('calls onRetry with the document id when its Retry button is clicked', async () => {
    const onRetry = vi.fn();
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={onRetry} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    const retryButtons = screen.getAllByRole('button', { name: /^retry$/i });
    await userEvent.click(retryButtons[0]!);
    expect(onRetry).toHaveBeenCalledWith(8421);
  });

  it('calls onRetryAll when the Retry-all button is clicked', async () => {
    const onRetryAll = vi.fn();
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={onRetryAll} onOpen={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /retry all/i }));
    expect(onRetryAll).toHaveBeenCalledTimes(1);
  });

  it('calls onOpen with the document id when the Preview button is clicked', async () => {
    const onOpen = vi.fn();
    render(
      <FailedDocumentsPanel documents={DOCS} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={onOpen} />,
    );
    const previewButtons = screen.getAllByRole('button', { name: /^preview$/i });
    await userEvent.click(previewButtons[0]!);
    expect(onOpen).toHaveBeenCalledWith(8421);
  });

  it('renders an all-clear message and no Retry-all button when the list is empty', () => {
    render(
      <FailedDocumentsPanel documents={[]} onRetry={vi.fn()} onRetryAll={vi.fn()} onOpen={vi.fn()} />,
    );
    expect(screen.getByText(/no failed documents/i)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /retry all/i }),
    ).not.toBeInTheDocument();
  });

  it('disables every Retry control while a retry is in flight', () => {
    render(
      <FailedDocumentsPanel
        documents={DOCS}
        onRetry={vi.fn()}
        onRetryAll={vi.fn()}
        onOpen={vi.fn()}
        retrying
      />,
    );
    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled();
    }
  });
});
