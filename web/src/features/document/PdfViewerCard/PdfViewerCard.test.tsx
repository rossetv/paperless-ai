import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PdfViewerCard } from './PdfViewerCard';

describe('PdfViewerCard', () => {
  it('renders an iframe pointing at the proxy URL', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
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
      />,
    );
    const link = screen.getByRole('link', { name: /download/i });
    expect(link.getAttribute('href')).toMatch(/\/api\/documents\/42\/pdf$/);
  });

  it('offers an Open in Paperless link', () => {
    render(
      <PdfViewerCard
        documentId={42}
        title="An invoice"
        paperlessUrl="https://p.example/documents/42/"
      />,
    );
    expect(
      screen.getByRole('link', { name: /open in paperless/i }),
    ).toHaveAttribute('href', 'https://p.example/documents/42/');
  });

  it('omits the Open in Paperless link when paperlessUrl is null', () => {
    render(<PdfViewerCard documentId={42} title="x" paperlessUrl={null} />);
    expect(
      screen.queryByRole('link', { name: /open in paperless/i }),
    ).not.toBeInTheDocument();
  });
});
