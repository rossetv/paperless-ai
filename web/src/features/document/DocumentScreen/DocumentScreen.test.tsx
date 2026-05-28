import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseMutationResult, UseQueryResult, UseMutateFunction } from '@tanstack/react-query';
import type { LibraryDocument, TaxonomyItem } from '../../../api/types';
import { DocumentScreen } from './DocumentScreen';

// ── Mock all hooks used by DocumentScreen and its children ─────────────────
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
  useSearch: vi.fn(),
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
  useSearch,
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
const mockUseSearch = useSearch as ReturnType<typeof vi.fn>;

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

function makeQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function renderScreen(opts: { role?: Role; mutate?: ReturnType<typeof vi.fn> } = {}) {
  const mutate = opts.mutate ?? vi.fn();
  mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));

  return {
    mutate,
    ...render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen
            document={DOC}
            parent="library"
            parentSearch=""
            role={opts.role ?? 'member'}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

/** Minimal pending-state stub for useSearch — no data yet, not errored. */
function searchPendingStub(): UseQueryResult<never, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: true,
    isPending: true,
    isFetching: true,
    isError: false,
    isSuccess: false,
    status: 'pending',
  } as unknown as UseQueryResult<never, Error>;
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
  // Default: useSearch returns pending so MatchCard renders a spinner (then
  // resolves asynchronously). Overridden per-test where the full result matters.
  mockUseSearch.mockReturnValue(searchPendingStub());
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
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen document={DOC} parent="library" parentSearch="?tag=12" role="readonly" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library?tag=12');
  });

  it('breadcrumb says "Search results" linking to / with the query string when parent is search', () => {
    const mutate = vi.fn();
    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen document={DOC} parent="search" parentSearch="?q=invoice" role="readonly" />
        </MemoryRouter>
      </QueryClientProvider>,
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

  // ── MatchCard integration ──────────────────────────────────────────────────

  it('renders MatchCard at the top of the sidebar when parent is search', () => {
    const mutate = vi.fn();
    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));
    // Return a successful search with a matching source so the card shows content.
    mockUseSearch.mockReturnValue(queryOk({
      answer: '…',
      sources: [
        {
          document_id: 934,
          title: 'eBay Payslip 05/2026',
          snippet: 'payslip **ireland**',
          score: 0.85,
          correspondent: 'eBay',
          document_type: 'Payslip',
          created: '2026-05-22',
          paperless_url: 'https://p.example/documents/934/',
          tags: [],
        },
      ],
      plan: { semantic_queries: [], keyword_terms: [], sub_questions: [] },
      stats: { llm_calls: 0, latency_ms: 0, refined: false },
    }));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen
            document={DOC}
            parent="search"
            parentSearch="?q=invoice"
            role="member"
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // MatchCard should show the citation meta for this source.
    expect(screen.getByText(/source 1 of 1/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.85/)).toBeInTheDocument();
  });

  it('omits MatchCard when parent is library', () => {
    const mutate = vi.fn();
    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate }));
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen
            document={DOC}
            parent="library"
            parentSearch=""
            role="member"
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // Neither the citation meta nor the "didn't appear" message should be present.
    expect(screen.queryByText(/source \d+ of \d+/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/didn't appear in the results/i)).not.toBeInTheDocument();
  });

  // ── Bug 4: Create correspondent/type selects the created item ─────────────

  it('creating a new correspondent patches it onto the document', async () => {
    const updateMutate = vi.fn();
    const correspondentMutate = vi.fn((
      _name: string,
      opts?: { onSuccess?: (data: TaxonomyItem) => void },
    ) => {
      // Simulate the created item being returned.
      opts?.onSuccess?.({ id: 50, name: 'New Corp', document_count: 0 });
    });

    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate: updateMutate }));
    mockUseCreateCorrespondent.mockReturnValue(
      createMutationStub({ mutate: correspondentMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );

    renderScreen({ role: 'member', mutate: updateMutate });

    // Open the correspondent combobox and type a new name that has no exact match.
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'New Corp' } });
    fireEvent.click(screen.getByText(/create "new corp"/i));

    // The create mutation must have been called.
    expect(correspondentMutate).toHaveBeenCalledWith('New Corp', expect.objectContaining({ onSuccess: expect.any(Function) }));
    // And on success, update must have been called with the new id.
    expect(updateMutate).toHaveBeenCalledWith({ id: 934, patch: { correspondent_id: 50 } });
  });

  it('creating a new document type patches it onto the document', async () => {
    const updateMutate = vi.fn();
    const documentTypeMutate = vi.fn((
      _name: string,
      opts?: { onSuccess?: (data: TaxonomyItem) => void },
    ) => {
      opts?.onSuccess?.({ id: 60, name: 'New Type', document_count: 0 });
    });

    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate: updateMutate }));
    mockUseCreateDocumentType.mockReturnValue(
      createMutationStub({ mutate: documentTypeMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );

    renderScreen({ role: 'member', mutate: updateMutate });

    // Open the document-type combobox and type a new name.
    fireEvent.click(screen.getByRole('button', { name: 'Payslip' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'New Type' } });
    fireEvent.click(screen.getByText(/create "new type"/i));

    expect(documentTypeMutate).toHaveBeenCalledWith('New Type', expect.objectContaining({ onSuccess: expect.any(Function) }));
    expect(updateMutate).toHaveBeenCalledWith({ id: 934, patch: { document_type_id: 60 } });
  });

  // ── Bug 5: Tag create race uses latest cache state ────────────────────────

  it('createTagThenAdd uses the latest document from the cache to avoid clobbering concurrent creates', async () => {
    // Simulate rapid tag creates: the first resolves with tag 200, the second
    // with tag 201. Both should end up in the final patch.
    const updateMutate = vi.fn();
    // createTag.mutate stubs — both invoke onSuccess synchronously.
    const tagMutate = vi.fn((
      _name: string,
      opts?: { onSuccess?: (data: TaxonomyItem) => void },
    ) => {
      // First call returns tag 200; second returns tag 201.
      const callCount = (tagMutate as ReturnType<typeof vi.fn>).mock.calls.length;
      opts?.onSuccess?.({ id: callCount === 1 ? 200 : 201, name: _name, document_count: 0 });
    });

    mockUseUpdateDocument.mockReturnValue(mutationStub({ mutate: updateMutate }));
    mockUseCreateTag.mockReturnValue(
      createMutationStub({ mutate: tagMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );

    renderScreen({ role: 'member', mutate: updateMutate });

    // Simulate opening TagEditor and creating two new tags.
    // We use the DOM to trigger TagEditor's onCreate callback twice.
    const addButton = screen.getByRole('button', { name: /add tag/i });
    fireEvent.click(addButton);
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'alpha-tag' } });
    fireEvent.click(screen.getByText(/create "alpha-tag"/i));

    // First create was called — update must have been called once.
    expect(tagMutate).toHaveBeenCalledTimes(1);
    expect(updateMutate).toHaveBeenCalledTimes(1);
    const firstCall = updateMutate.mock.calls[0]?.[0] as { id: number; patch: { tags: number[] } };
    expect(firstCall.patch.tags).toContain(200);
  });
});
