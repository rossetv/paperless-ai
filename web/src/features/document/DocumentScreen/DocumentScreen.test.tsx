import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DocumentScreen } from './DocumentScreen';
import type { LibraryDocument } from '../../../api/types';

const DOC: LibraryDocument = {
  id: 934,
  title: 'eBay Payslip 05/2026',
  correspondent: 'eBay',
  document_type: 'Payslip',
  created: '2026-05-22',
  tags: ['2026', 'ireland', 'payroll'],
  page_count: 1,
  paperless_url: 'https://p.example/documents/934/',
};

describe('DocumentScreen', () => {
  it('renders the title, submeta, PDF viewer, and details card', () => {
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="library" parentSearch="" canEdit={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: 'eBay Payslip 05/2026' })).toBeInTheDocument();
    expect(screen.getByText(/#934/)).toBeInTheDocument();
    expect(screen.getByText(/1 page/i)).toBeInTheDocument();
    expect(screen.getByText('eBay')).toBeInTheDocument();
    expect(screen.getByText('Payslip')).toBeInTheDocument();
    expect(screen.getByText('22 May 2026')).toBeInTheDocument();
    expect(screen.getByTitle(/ebay payslip 05\/2026 pdf/i)).toBeInTheDocument();
  });

  it('breadcrumb says "Library" linking to /library when parent is library and no parent search', () => {
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="library" parentSearch="" canEdit={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library');
  });

  it('breadcrumb preserves parent search-string for library', () => {
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="library" parentSearch="?tag=12" canEdit={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library?tag=12');
  });

  it('breadcrumb says "Search results" linking to / with the query string when parent is search', () => {
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="search" parentSearch="?q=invoice" canEdit={false} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /search results/i })).toHaveAttribute('href', '/?q=invoice');
  });
});
