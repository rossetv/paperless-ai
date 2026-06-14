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

  it('shows no action toolbar in the normal state (actions live in the page header)', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
        downloadFilename="An invoice.pdf"
      />,
    );
    // Download / Open-in-Paperless were moved out of the card to DocumentActions;
    // the card only surfaces them in the load-error escape hatch (below).
    expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument();
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
      // Escape hatches are offered inside the error state via DocumentActions.
      expect(
        screen.getByRole('link', { name: /download/i }).getAttribute('href'),
      ).toMatch(/\/api\/documents\/42\/pdf$/);
      expect(
        screen.getByRole('link', { name: /open in paperless/i }),
      ).toHaveAttribute('href', 'https://p.example/documents/42/');
    });
  });
});
