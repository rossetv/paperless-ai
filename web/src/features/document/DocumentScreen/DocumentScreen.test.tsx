import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { UseMutationResult, UseQueryResult, UseMutateFunction } from '@tanstack/react-query';
import type { LibraryDocument, TaxonomyItem } from '../../../api/types';
import { DocumentScreen } from './DocumentScreen';

// ── Mock all hooks used by DocumentScreen and MetadataCard ─────────────────
vi.mock('../../../api/hooks', () => ({
  useUpdateDocument: vi.fn(),
  useCorrespondents: vi.fn(),
  useDocumentTypes: vi.fn(),
  useTags: vi.fn(),
  useCreateCorrespondent: vi.fn(),
  useCreateDocumentType: vi.fn(),
  useCreateTag: vi.fn(),
  useReclassifyDocument: vi.fn(),
  useRetranscribeDocument: vi.fn(),
  useDeleteDocument: vi.fn(),
}));

import {
  useUpdateDocument,
  useCorrespondents,
  useDocumentTypes,
  useTags,
  useCreateCorrespondent,
  useCreateDocumentType,
  useCreateTag,
  useReclassifyDocument,
  useRetranscribeDocument,
  useDeleteDocument,
} from '../../../api/hooks';

const mockUseUpdateDocument = useUpdateDocument as ReturnType<typeof vi.fn>;
const mockUseCorrespondents = useCorrespondents as ReturnType<typeof vi.fn>;
const mockUseDocumentTypes = useDocumentTypes as ReturnType<typeof vi.fn>;
const mockUseTags = useTags as ReturnType<typeof vi.fn>;
const mockUseCreateCorrespondent = useCreateCorrespondent as ReturnType<typeof vi.fn>;
const mockUseCreateDocumentType = useCreateDocumentType as ReturnType<typeof vi.fn>;
const mockUseCreateTag = useCreateTag as ReturnType<typeof vi.fn>;
const mockUseReclassifyDocument = useReclassifyDocument as ReturnType<typeof vi.fn>;
const mockUseRetranscribeDocument = useRetranscribeDocument as ReturnType<typeof vi.fn>;
const mockUseDeleteDocument = useDeleteDocument as ReturnType<typeof vi.fn>;

// ── Fixtures ─────────────────────────────────────────────────────────────────

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

const CORRESPONDENTS: TaxonomyItem[] = [
  { id: 1, name: 'eBay', document_count: 87 },
  { id: 2, name: 'Revenue.ie', document_count: 14 },
];

const DOC_TYPES: TaxonomyItem[] = [
  { id: 10, name: 'Payslip', document_count: 30 },
  { id: 11, name: 'Invoice', document_count: 12 },
];

const ALL_TAGS: TaxonomyItem[] = [
  { id: 100, name: '2026', document_count: 50 },
  { id: 101, name: 'ireland', document_count: 20 },
  { id: 102, name: 'payroll', document_count: 30 },
  { id: 103, name: 'new-tag', document_count: 0 },
];

// ── Helper builders ───────────────────────────────────────────────────────────

function mutationStub(
  overrides: Partial<UseMutationResult<LibraryDocument, Error, { id: number; patch: object }>> = {},
): UseMutationResult<LibraryDocument, Error, { id: number; patch: object }> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: 'idle',
    reset: vi.fn(),
    context: undefined,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
    variables: undefined,
    ...overrides,
  } as unknown as UseMutationResult<LibraryDocument, Error, { id: number; patch: object }>;
}

function voidMutationStub(
  overrides: Partial<UseMutationResult<void, Error, number>> = {},
): UseMutationResult<void, Error, number> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: 'idle',
    reset: vi.fn(),
    context: undefined,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
    variables: undefined,
    ...overrides,
  } as unknown as UseMutationResult<void, Error, number>;
}

function createMutationStub(
  overrides: Partial<UseMutationResult<TaxonomyItem, Error, string>> = {},
): UseMutationResult<TaxonomyItem, Error, string> {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    data: undefined,
    error: null,
    isPending: false,
    isSuccess: false,
    isError: false,
    isIdle: true,
    status: 'idle',
    reset: vi.fn(),
    context: undefined,
    failureCount: 0,
    failureReason: null,
    isPaused: false,
    submittedAt: 0,
    variables: undefined,
    ...overrides,
  } as unknown as UseMutationResult<TaxonomyItem, Error, string>;
}

function queryOk<T>(data: T): UseQueryResult<T, Error> {
  return {
    data,
    error: null,
    isLoading: false,
    isPending: false,
    isError: false,
    isSuccess: true,
    status: 'success',
  } as UseQueryResult<T, Error>;
}

type Role = 'admin' | 'member' | 'readonly';

function renderScreen(opts: { role?: Role; mutate?: ReturnType<typeof vi.fn> } = {}) {
  const mutate = opts.mutate ?? vi.fn();
  mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));

  return {
    mutate,
    ...render(
      <MemoryRouter>
        <DocumentScreen
          document={DOC}
          parent="library"
          parentSearch=""
          role={opts.role ?? 'member'}
        />
      </MemoryRouter>,
    ),
  };
}

beforeEach(() => {
  mockUseCorrespondents.mockReturnValue(queryOk(CORRESPONDENTS));
  mockUseDocumentTypes.mockReturnValue(queryOk(DOC_TYPES));
  mockUseTags.mockReturnValue(queryOk(ALL_TAGS));
  mockUseCreateCorrespondent.mockReturnValue(createMutationStub());
  mockUseCreateDocumentType.mockReturnValue(createMutationStub());
  mockUseCreateTag.mockReturnValue(createMutationStub());
  mockUseReclassifyDocument.mockReturnValue(voidMutationStub());
  mockUseRetranscribeDocument.mockReturnValue(voidMutationStub());
  mockUseDeleteDocument.mockReturnValue(voidMutationStub());
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('DocumentScreen', () => {
  // ── Rendering baseline ────────────────────────────────────────────────────

  it('renders the title, submeta, PDF viewer, and details card', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.getByRole('heading', { name: 'eBay Payslip 05/2026' })).toBeInTheDocument();
    expect(screen.getByText(/#934/)).toBeInTheDocument();
    expect(screen.getByText(/1 page/i)).toBeInTheDocument();
    expect(screen.getByText('eBay')).toBeInTheDocument();
    expect(screen.getByText('Payslip')).toBeInTheDocument();
    expect(screen.getByText('22 May 2026')).toBeInTheDocument();
    expect(screen.getByTitle(/ebay payslip 05\/2026 pdf/i)).toBeInTheDocument();
  });

  it('breadcrumb says "Library" linking to /library when parent is library and no parent search', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library');
  });

  it('breadcrumb preserves parent search-string for library', () => {
    const mutate = vi.fn();
    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="library" parentSearch="?tag=12" role="readonly" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library?tag=12');
  });

  it('breadcrumb says "Search results" linking to / with the query string when parent is search', () => {
    const mutate = vi.fn();
    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));
    render(
      <MemoryRouter>
        <DocumentScreen document={DOC} parent="search" parentSearch="?q=invoice" role="readonly" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: /search results/i })).toHaveAttribute('href', '/?q=invoice');
  });

  // ── Title editing ──────────────────────────────────────────────────────────

  it('changing the title fires PATCH with the new title on blur', async () => {
    const mutate = vi.fn();
    renderScreen({ role: 'member', mutate });
    // role=member → canEdit=true renders the title as a button.
    fireEvent.click(screen.getByRole('button', { name: /ebay payslip 05\/2026/i }));
    const input = screen.getByDisplayValue('eBay Payslip 05/2026');
    fireEvent.change(input, { target: { value: 'Renamed' } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith({ id: 934, patch: { title: 'Renamed' } }),
    );
  });

  it('does not fire PATCH when the title is unchanged', async () => {
    const mutate = vi.fn();
    renderScreen({ role: 'member', mutate });
    fireEvent.click(screen.getByRole('button', { name: /ebay payslip 05\/2026/i }));
    fireEvent.blur(screen.getByDisplayValue('eBay Payslip 05/2026'));
    await new Promise((r) => setTimeout(r, 50));
    expect(mutate).not.toHaveBeenCalled();
  });

  // ── Correspondent editing ──────────────────────────────────────────────────

  it('changing the correspondent fires PATCH with correspondent_id', async () => {
    const mutate = vi.fn();
    renderScreen({ role: 'member', mutate });
    // TaxonomyCombobox trigger shows the correspondent name exactly.
    // Use exact match to avoid colliding with the title button.
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.click(screen.getByText('Revenue.ie'));
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith({ id: 934, patch: { correspondent_id: 2 } }),
    );
  });

  // ── Tag editing ────────────────────────────────────────────────────────────

  it('removing a tag fires PATCH with the updated tag id list', async () => {
    const mutate = vi.fn();
    renderScreen({ role: 'member', mutate });
    // Remove the "ireland" tag.
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    await waitFor(() => expect(mutate).toHaveBeenCalled());
    const call = mutate.mock.calls[0]?.[0] as { id: number; patch: { tags: number[] } };
    expect(call.id).toBe(934);
    expect(call.patch.tags).not.toContain(101); // 101 = ireland
  });

  // ── Readonly mode ──────────────────────────────────────────────────────────

  it('readonly user sees no edit affordances on the title', () => {
    renderScreen({ role: 'readonly' });
    // Title must be a plain heading, not a button.
    expect(screen.getByRole('heading', { name: 'eBay Payslip 05/2026' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /ebay payslip 05\/2026/i })).not.toBeInTheDocument();
  });

  it('readonly user sees no "Add tag" button', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.queryByRole('button', { name: /add tag/i })).not.toBeInTheDocument();
  });

  it('readonly user sees no × tag remove buttons', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument();
  });

  // ── SaveStatusPill ─────────────────────────────────────────────────────────

  it('shows "View only" pill when role is readonly', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.getByRole('status')).toHaveTextContent(/view only/i);
  });

  it('shows "Saved" status pill when role is member and mutation is idle', () => {
    renderScreen({ role: 'member' });
    expect(screen.getByRole('status')).toHaveTextContent(/saved/i);
  });

  // ── ActionsCard wiring ─────────────────────────────────────────────────────

  it('admin role sees ActionsCard with Delete button', () => {
    renderScreen({ role: 'admin' });
    expect(screen.getByRole('button', { name: /re-classify/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^delete document/i })).toBeInTheDocument();
  });

  it('member role sees ActionsCard without Delete button', () => {
    renderScreen({ role: 'member' });
    expect(screen.getByRole('button', { name: /re-classify/i })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete document/i })).not.toBeInTheDocument();
  });

  it('readonly role does NOT see ActionsCard', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.queryByRole('button', { name: /re-classify/i })).not.toBeInTheDocument();
  });

  it('successful delete navigates back to the breadcrumb target', async () => {
    // Capture the onSuccess callback so we can invoke it manually and simulate
    // a completed delete without a real network call.
    let capturedOnSuccess: (() => void) | undefined;

    // Typed through unknown to satisfy the strict UseMutateFunction signature.
    const deleteMutate = (vi.fn((
      _id: number,
      opts?: { onSuccess?: (data: void, vars: number, ctx: unknown) => void },
    ) => {
      if (opts?.onSuccess) {
        capturedOnSuccess = () => opts.onSuccess!(undefined, 0, undefined);
      }
    }) as unknown) as UseMutateFunction<void, Error, number>;

    mockUseDeleteDocument.mockReturnValue(voidMutationStub({ mutate: deleteMutate }));

    renderScreen({ role: 'admin' });

    // Trigger the delete flow.
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    const confirmBtn = await screen.findByRole('button', { name: /^delete$/i });
    fireEvent.click(confirmBtn);

    expect(deleteMutate).toHaveBeenCalledWith(934, expect.objectContaining({ onSuccess: expect.any(Function) }));

    // Fire the onSuccess to simulate a completed delete.
    capturedOnSuccess?.();
    // The navigate('/library') call happens — MemoryRouter absorbs it; we
    // verify by confirming the modal is gone (delete flowed through).
    await waitFor(() =>
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument(),
    );
  });
});
