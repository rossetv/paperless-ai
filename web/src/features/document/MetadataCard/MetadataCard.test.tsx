import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import type { TaxonomyItem } from '../../../api/types';
import type { LibraryDocument } from '../../../api/types';
import { MetadataCard } from './MetadataCard';

const CORRESPONDENTS: TaxonomyItem[] = [
  { id: 1, name: 'eBay', document_count: 87 },
  { id: 2, name: 'Revenue.ie', document_count: 14 },
];

const DOC_TYPES: TaxonomyItem[] = [
  { id: 10, name: 'Payslip', document_count: 30 },
  { id: 11, name: 'Invoice', document_count: 12 },
];

const DOC: LibraryDocument = {
  id: 934,
  title: 'eBay Payslip 05/2026',
  correspondent: 'eBay',
  document_type: 'Payslip',
  created: '2026-05-22',
  tags: ['2026', 'ireland'],
  page_count: 1,
  paperless_url: 'https://p.example/documents/934/',
};

const DOC_EMPTY: LibraryDocument = {
  id: 935,
  title: null,
  correspondent: null,
  document_type: null,
  created: null,
  tags: [],
  page_count: null,
  paperless_url: 'https://p.example/documents/935/',
};

describe('MetadataCard', () => {
  it('renders correspondent and document type in read-only mode', () => {
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={false}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    expect(screen.getByText('eBay')).toBeInTheDocument();
    expect(screen.getByText('Payslip')).toBeInTheDocument();
  });

  it('renders the formatted document date', () => {
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={false}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    expect(screen.getByText('22 May 2026')).toBeInTheDocument();
  });

  it('formats a full offset timestamp from the API, never the raw ISO', () => {
    // The real API returns the date as a full offset timestamp; the row must
    // show the human date, not the raw "2026-01-13T00:00:00+00:00".
    const doc: LibraryDocument = { ...DOC, created: '2026-01-13T00:00:00+00:00' };
    render(
      <MetadataCard
        document={doc}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={false}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    expect(screen.getByText('13 January 2026')).toBeInTheDocument();
    expect(screen.queryByText('2026-01-13T00:00:00+00:00')).not.toBeInTheDocument();
  });

  it('shows the formatted date in editable view mode (not the raw ISO)', () => {
    const doc: LibraryDocument = { ...DOC, created: '2026-01-13T00:00:00+00:00' };
    render(
      <MetadataCard
        document={doc}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    // The view button reads as the formatted date, and the underlying date
    // input pre-fills with the bare YYYY-MM-DD the native control accepts.
    fireEvent.click(screen.getByRole('button', { name: /13 January 2026/i }));
    expect(screen.getByDisplayValue('2026-01-13')).toBeInTheDocument();
  });

  it('shows "—" for null taxonomy fields and "No date" for null created', () => {
    render(
      <MetadataCard
        document={DOC_EMPTY}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={false}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    // TaxonomyCombobox renders "—" for null selectedId.
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(2);
    // Date row renders "No date" (consistent with the rest of the codebase).
    expect(screen.getByText('No date')).toBeInTheDocument();
  });

  it('canEdit=true renders interactive comboboxes (trigger buttons)', () => {
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={vi.fn()}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    // TaxonomyCombobox shows a trigger button with the current value.
    expect(screen.getByRole('button', { name: /ebay/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /payslip/i })).toBeInTheDocument();
  });

  it('calls onPatch with correspondent_id when a correspondent is selected', () => {
    const onPatch = vi.fn();
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={onPatch}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    // Open the correspondent combobox.
    fireEvent.click(screen.getByRole('button', { name: /ebay/i }));
    // Select "Revenue.ie".
    fireEvent.click(screen.getByText('Revenue.ie'));
    expect(onPatch).toHaveBeenCalledWith({ correspondent_id: 2 });
  });

  it('calls onPatch with document_type_id when a type is selected', () => {
    const onPatch = vi.fn();
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={onPatch}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /payslip/i }));
    fireEvent.click(screen.getByText('Invoice'));
    expect(onPatch).toHaveBeenCalledWith({ document_type_id: 11 });
  });

  it('calls onCreateCorrespondent when the user creates a new correspondent', () => {
    const onCreateCorrespondent = vi.fn();
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={vi.fn()}
        onCreateCorrespondent={onCreateCorrespondent}
        onCreateDocumentType={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /ebay/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Brand New Co' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));
    expect(onCreateCorrespondent).toHaveBeenCalledWith('Brand New Co');
  });

  it('calls onPatch with document_date when the date field is committed', () => {
    const onPatch = vi.fn();
    render(
      <MetadataCard
        document={DOC}
        correspondents={CORRESPONDENTS}
        documentTypes={DOC_TYPES}
        canEdit={true}
        onPatch={onPatch}
        onCreateCorrespondent={vi.fn()}
        onCreateDocumentType={vi.fn()}
      />,
    );
    // EditableField for date — the view button shows the formatted date; click
    // it to enter edit mode, where the input carries the bare ISO.
    fireEvent.click(screen.getByRole('button', { name: /22 May 2026/i }));
    const input = screen.getByDisplayValue('2026-05-22');
    fireEvent.change(input, { target: { value: '2026-06-01' } });
    fireEvent.blur(input);
    expect(onPatch).toHaveBeenCalledWith({ document_date: '2026-06-01' });
  });
});
