import React from 'react';
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { PdfViewerCard } from './PdfViewerCard';

describe('PdfViewerCard', () => {
  it('renders an iframe pointing at the proxy URL', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
        downloadFilename="An invoice.pdf"
      />,
    );
    const frame = screen.getByTitle(/an invoice/i);
    expect(frame.tagName).toBe('IFRAME');
    expect(frame.getAttribute('src')).toMatch(/\/api\/documents\/42\/pdf$/);
  });

  it('offers a Download link to the proxy URL', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
        downloadFilename="An invoice.pdf"
      />,
    );
    const link = screen.getByRole('link', { name: /download/i });
    expect(link.getAttribute('href')).toMatch(/\/api\/documents\/42\/pdf$/);
  });

  it('sets the download attribute to the supplied filename so the browser names the file correctly', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
        downloadFilename="An invoice.pdf"
      />,
    );
    const link = screen.getByRole('link', { name: /download/i });
    expect(link.getAttribute('download')).toBe('An invoice.pdf');
  });

  it('offers an Open in Paperless link', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
        downloadFilename="An invoice.pdf"
      />,
    );
    expect(
      screen.getByRole('link', { name: /open in paperless/i }),
    ).toHaveAttribute('href', 'https://p.example/documents/42/');
  });

  it('omits the Open in Paperless link when paperlessUrl is null', () => {
    render(<PdfViewerCard documentId={42} title="x" paperlessUrl={null} downloadFilename="x.pdf" />);
    expect(
      screen.queryByRole('link', { name: /open in paperless/i }),
    ).not.toBeInTheDocument();
  });

  describe('load failure', () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('shows no error overlay before the frame fails', () => {
      render(
        <PdfViewerCard documentId={42} title="An invoice" paperlessUrl={null} downloadFilename="An invoice.pdf" />,
      );
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('shows an app-owned error state with escape hatches when the frame fails', () => {
      render(
        <PdfViewerCard
          documentId={42}
          title="An invoice"
          paperlessUrl="https://p.example/documents/42/"
          downloadFilename="An invoice.pdf"
        />,
      );
      // The frame never loads — surface the dark app error state.
      act(() => {
        vi.advanceTimersByTime(8000);
      });
      const alert = screen.getByRole('alert');
      expect(alert).toHaveTextContent(/couldn't load the preview/i);
      // Escape hatches are offered inside the error state, alongside the toolbar.
      expect(screen.getAllByRole('link', { name: /download/i }).length).toBeGreaterThanOrEqual(2);
      expect(
        screen.getAllByRole('link', { name: /open in paperless/i }).length,
      ).toBeGreaterThanOrEqual(2);
    });
  });
});
