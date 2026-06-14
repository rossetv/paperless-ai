import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DocumentActions } from './DocumentActions';

describe('DocumentActions', () => {
  it('offers a Download link to the pdf URL with the supplied filename', () => {
    render(
      <DocumentActions
        pdfUrl="/api/documents/42/pdf"
        downloadFilename="An invoice.pdf"
        paperlessUrl="https://p.example/documents/42/"
      />,
    );
    const link = screen.getByRole('link', { name: /download/i });
    expect(link).toHaveAttribute('href', '/api/documents/42/pdf');
    expect(link).toHaveAttribute('download', 'An invoice.pdf');
  });

  it('offers an Open in Paperless link to the source instance', () => {
    render(
      <DocumentActions
        pdfUrl="/api/documents/42/pdf"
        downloadFilename="x.pdf"
        paperlessUrl="https://p.example/documents/42/"
      />,
    );
    expect(
      screen.getByRole('link', { name: /open in paperless/i }),
    ).toHaveAttribute('href', 'https://p.example/documents/42/');
  });

  it('omits the Open in Paperless link when paperlessUrl is null', () => {
    render(
      <DocumentActions pdfUrl="/api/documents/42/pdf" downloadFilename="x.pdf" paperlessUrl={null} />,
    );
    expect(
      screen.queryByRole('link', { name: /open in paperless/i }),
    ).not.toBeInTheDocument();
  });
});
