import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UseMutationResult, UseQueryResult, UseMutateFunction } from '@tanstack/react-query';
import type { LibraryDocument, TaxonomyItem } from '../../../api/types';
import { ApiError, patchDocument, getDocument, deleteDocument } from '../../../api/client';
import { useDocument } from '../../../api/hooks/library';
import { DocumentScreen } from './DocumentScreen';

// The save queue lives in TanStack's callback timing, so the real update hook
// runs against a mocked HTTP layer.
vi.mock('../../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/client')>()),
  patchDocument: vi.fn(),
  getDocument: vi.fn(),
  deleteDocument: vi.fn(),
}));

vi.mock('../../../api/hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../api/hooks')>()),
  useCorrespondents: vi.fn(),
  useDocumentTypes: vi.fn(),
  useTags: vi.fn(),
  useCreateCorrespondent: vi.fn(),
  useCreateDocumentType: vi.fn(),
  useCreateTag: vi.fn(),
  useReclassifyDocument: vi.fn(),
  useRetranscribeDocument: vi.fn(),
  useSearch: vi.fn(),
}));

import {
  useCorrespondents,
  useDocumentTypes,
  useTags,
  useCreateCorrespondent,
  useCreateDocumentType,
  useCreateTag,
  useReclassifyDocument,
  useRetranscribeDocument,
  useSearch,
} from '../../../api/hooks';

const mockPatchDocument = patchDocument as ReturnType<typeof vi.fn>;
const mockGetDocument = getDocument as ReturnType<typeof vi.fn>;
const mockUseCorrespondents = useCorrespondents as ReturnType<typeof vi.fn>;
const mockUseDocumentTypes = useDocumentTypes as ReturnType<typeof vi.fn>;
const mockUseTags = useTags as ReturnType<typeof vi.fn>;
const mockUseCreateCorrespondent = useCreateCorrespondent as ReturnType<typeof vi.fn>;
const mockUseCreateDocumentType = useCreateDocumentType as ReturnType<typeof vi.fn>;
const mockUseCreateTag = useCreateTag as ReturnType<typeof vi.fn>;
const mockUseReclassifyDocument = useReclassifyDocument as ReturnType<typeof vi.fn>;
const mockUseRetranscribeDocument = useRetranscribeDocument as ReturnType<typeof vi.fn>;
const mockDeleteDocument = deleteDocument as ReturnType<typeof vi.fn>;
const mockUseSearch = useSearch as ReturnType<typeof vi.fn>;

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

/** Resolvable from the test, for a request that is still in flight. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Reads the document from the cache as the pages do, so a save's refetch reaches the screen. */
function LiveScreen({ role }: { role: Role }): React.ReactElement | null {
  const doc = useDocument(DOC.id);
  return doc.data ? <DocumentScreen document={doc.data} parent="library" parentSearch="" role={role} /> : null;
}

function renderScreen(opts: { role?: Role; queryClient?: QueryClient; live?: boolean } = {}) {
  const queryClient = opts.queryClient ?? makeQueryClient();
  const role = opts.role ?? 'member';
  if (opts.live) queryClient.setQueryData(['document', DOC.id], DOC);
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        {opts.live ? (
          <LiveScreen role={role} />
        ) : (
          <DocumentScreen document={DOC} parent="library" parentSearch="" role={role} />
        )}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The patch of each PATCH request sent so far. */
function sentPatches(): object[] {
  return mockPatchDocument.mock.calls.map((c) => c[1] as object);
}

function renameTitle(to: string): void {
  fireEvent.click(screen.getByRole('button', { name: /ebay payslip 05\/2026/i }));
  const input = screen.getByDisplayValue('eBay Payslip 05/2026');
  fireEvent.change(input, { target: { value: to } });
  fireEvent.blur(input);
}

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
  mockPatchDocument.mockReset().mockResolvedValue(DOC);
  // The search index lags behind Paperless: a read right after a save still has the old values.
  mockGetDocument.mockReset().mockResolvedValue(DOC);
  mockUseCorrespondents.mockReturnValue(queryOk(CORRESPONDENTS));
  mockUseDocumentTypes.mockReturnValue(queryOk(DOC_TYPES));
  mockUseTags.mockReturnValue(queryOk(ALL_TAGS));
  mockUseCreateCorrespondent.mockReturnValue(createMutationStub());
  mockUseCreateDocumentType.mockReturnValue(createMutationStub());
  mockUseCreateTag.mockReturnValue(createMutationStub());
  mockUseReclassifyDocument.mockReturnValue(voidMutationStub());
  mockUseRetranscribeDocument.mockReturnValue(voidMutationStub());
  mockDeleteDocument.mockReset().mockResolvedValue(undefined);
  // Pending by default; tests that need MatchCard content override it.
  mockUseSearch.mockReturnValue(searchPendingStub());
});

describe('DocumentScreen', () => {
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
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter>
          <DocumentScreen document={DOC} parent="search" parentSearch="?q=invoice" role="readonly" />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole('link', { name: /search results/i })).toHaveAttribute('href', '/?q=invoice');
  });

  it('Download anchor carries the document title as the suggested filename', () => {
    renderScreen({ role: 'readonly' });
    // The "/" in 'eBay Payslip 05/2026' is stripped.
    const link = screen.getByRole('link', { name: /^download$/i });
    expect(link.getAttribute('download')).toBe('eBay Payslip 052026.pdf');
  });

  it('changing the title fires PATCH with the new title on blur', async () => {
    renderScreen({ role: 'member' });
    renameTitle('Renamed');
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledWith(934, { title: 'Renamed' }));
  });

  it('does not fire PATCH when the title is unchanged', async () => {
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /ebay payslip 05\/2026/i }));
    fireEvent.blur(screen.getByDisplayValue('eBay Payslip 05/2026'));
    await new Promise((r) => setTimeout(r, 50));
    expect(mockPatchDocument).not.toHaveBeenCalled();
  });

  it('changing the correspondent fires PATCH with correspondent_id', async () => {
    renderScreen({ role: 'member' });
    // Exact match, so it does not hit the title button.
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.click(screen.getByText('Revenue.ie'));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledWith(934, { correspondent_id: 2 }));
  });

  it('removing a tag fires PATCH with the updated tag id list', async () => {
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    // 101 = ireland
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledWith(934, { tags: [100, 102] }));
  });

  it('does not offer tag editing before the tag list has loaded', () => {
    mockUseTags.mockReturnValue({ ...queryOk(undefined), isPending: true, isSuccess: false, status: 'pending' });
    renderScreen({ role: 'member' });
    expect(screen.queryByRole('button', { name: /add tag/i })).not.toBeInTheDocument();
  });

  it('refetches a stale tag list so a tag missing from it is not dropped', async () => {
    const stale = ALL_TAGS.filter((t) => t.name !== 'payroll');
    const refetch = vi.fn().mockResolvedValue({ data: ALL_TAGS });
    mockUseTags.mockReturnValue({ ...queryOk(stale), refetch });
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalled());
    expect(sentPatches()[0]).toEqual({ tags: [100, 102] });
  });

  it('sends no tag patch and shows an error when a document tag cannot be resolved', async () => {
    const stale = ALL_TAGS.filter((t) => t.name !== 'payroll');
    const refetch = vi.fn().mockResolvedValue({ data: stale });
    mockUseTags.mockReturnValue({ ...queryOk(stale), refetch });
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/tags/i);
    expect(mockPatchDocument).not.toHaveBeenCalled();
  });

  it('says the tag list could not be loaded when its refetch fails, and sends nothing', async () => {
    const stale = ALL_TAGS.filter((t) => t.name !== 'payroll');
    const refetch = vi.fn().mockResolvedValue({ data: stale, status: 'error', isError: true, error: new Error('down') });
    mockUseTags.mockReturnValue({ ...queryOk(stale), refetch });
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/tag list/i);
    expect(mockPatchDocument).not.toHaveBeenCalled();
  });

  it('readonly user sees no edit affordances on the title', () => {
    renderScreen({ role: 'readonly' });
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

  it('shows "View only" pill when role is readonly', () => {
    renderScreen({ role: 'readonly' });
    expect(screen.getByRole('status')).toHaveTextContent(/view only/i);
  });

  it('shows no "Saved" before anything has been saved', () => {
    renderScreen({ role: 'member' });
    expect(screen.getByRole('status')).not.toHaveTextContent(/saved/i);
  });

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
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={['/document/934']}>
          <Routes>
            <Route
              path="/document/934"
              element={<DocumentScreen document={DOC} parent="library" parentSearch="" role="admin" />}
            />
            <Route path="/library" element={<p>library page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^delete$/i }));
    expect(await screen.findByText('library page')).toBeInTheDocument();
    expect(mockDeleteDocument).toHaveBeenCalledWith(934, expect.anything());
  });

  it('a failed delete shows the server error in the dialog and stays on the document', async () => {
    mockDeleteDocument.mockRejectedValue(new ApiError(403, undefined, 'Admins only'));
    renderScreen({ role: 'admin' });
    fireEvent.click(screen.getByRole('button', { name: /^delete document/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^delete$/i }));
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('Admins only');
    expect(screen.getByText(/#934/)).toBeInTheDocument();
  });

  it('re-classify confirms it was queued', async () => {
    const reclassifyMutate = vi.fn((_id: number, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
    mockUseReclassifyDocument.mockReturnValue(
      voidMutationStub({ mutate: reclassifyMutate as unknown as UseMutateFunction<void, Error, number> }),
    );
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /re-classify/i }));
    expect(reclassifyMutate).toHaveBeenCalledWith(934, expect.anything());
    expect(await screen.findByText(/re-classif/i, { selector: '[role="status"] *' })).toBeInTheDocument();
  });

  it('a second info toast stays for its own full time', () => {
    vi.useFakeTimers();
    try {
      const succeed = vi.fn((_id: number, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.());
      const stub = voidMutationStub({ mutate: succeed as unknown as UseMutateFunction<void, Error, number> });
      mockUseReclassifyDocument.mockReturnValue(stub);
      mockUseRetranscribeDocument.mockReturnValue(stub);
      renderScreen({ role: 'member' });

      fireEvent.click(screen.getByRole('button', { name: /re-classify/i }));
      act(() => vi.advanceTimersByTime(5_000));
      fireEvent.click(screen.getByRole('button', { name: /re-transcribe/i }));
      act(() => vi.advanceTimersByTime(1_500));
      expect(screen.getByText(/re-transcription/i)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it('a failed re-transcribe shows the server error', async () => {
    const retranscribeMutate = vi.fn((_id: number, opts?: { onError?: (err: Error) => void }) =>
      opts?.onError?.(new ApiError(503, undefined, 'OCR is turned off')),
    );
    mockUseRetranscribeDocument.mockReturnValue(
      voidMutationStub({ mutate: retranscribeMutate as unknown as UseMutateFunction<void, Error, number> }),
    );
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /re-transcribe/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('OCR is turned off');
  });

  it('re-transcribe is disabled while its request runs', () => {
    mockUseRetranscribeDocument.mockReturnValue(voidMutationStub({ isPending: true }));
    renderScreen({ role: 'member' });
    expect(screen.getByRole('button', { name: /re-transcribe/i })).toBeDisabled();
  });

  it('a failed tag create shows the error', async () => {
    const tagMutate = vi.fn((_name: string, opts?: { onError?: (err: Error) => void }) =>
      opts?.onError?.(new Error('network down')),
    );
    mockUseCreateTag.mockReturnValue(
      createMutationStub({ mutate: tagMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'alpha-tag' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/tag/i);
  });

  it.each([
    { kind: 'tag', opener: /add tag/i, hook: () => mockUseCreateTag },
    { kind: 'correspondent', opener: 'eBay', hook: () => mockUseCreateCorrespondent },
    { kind: 'document type', opener: 'Payslip', hook: () => mockUseCreateDocumentType },
  ])('creates no second $kind while the first create runs', ({ opener, hook }) => {
    const create = vi.fn();
    hook().mockReturnValue(
      createMutationStub({ mutate: create as unknown as UseMutateFunction<TaxonomyItem, Error, string>, isPending: true }),
    );
    renderScreen({ role: 'member' });
    fireEvent.click(screen.getByRole('button', { name: opener }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Brand new' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));
    expect(create).not.toHaveBeenCalled();
  });

  it('renders MatchCard at the top of the sidebar when parent is search', () => {
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
      plan: { specs: [] },
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
    expect(screen.getByText(/source 1 of 1/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.85/)).toBeInTheDocument();
  });

  it('omits MatchCard when parent is library', () => {
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
    expect(screen.queryByText(/source \d+ of \d+/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/didn't appear in the results/i)).not.toBeInTheDocument();
  });

  it('creating a new correspondent patches it onto the document', async () => {
    const correspondentMutate = vi.fn((
      _name: string,
      opts?: { onSuccess?: (data: TaxonomyItem) => void },
    ) => {
      opts?.onSuccess?.({ id: 50, name: 'New Corp', document_count: 0 });
    });

    mockUseCreateCorrespondent.mockReturnValue(
      createMutationStub({ mutate: correspondentMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );

    renderScreen({ role: 'member' });

    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'New Corp' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));

    expect(correspondentMutate).toHaveBeenCalledWith('New Corp', expect.objectContaining({ onSuccess: expect.any(Function) }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledWith(934, { correspondent_id: 50 }));
  });

  it('creating a new document type patches it onto the document', async () => {
    const documentTypeMutate = vi.fn((
      _name: string,
      opts?: { onSuccess?: (data: TaxonomyItem) => void },
    ) => {
      opts?.onSuccess?.({ id: 60, name: 'New Type', document_count: 0 });
    });

    mockUseCreateDocumentType.mockReturnValue(
      createMutationStub({ mutate: documentTypeMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );

    renderScreen({ role: 'member' });

    fireEvent.click(screen.getByRole('button', { name: 'Payslip' }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'New Type' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));

    expect(documentTypeMutate).toHaveBeenCalledWith('New Type', expect.objectContaining({ onSuccess: expect.any(Function) }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledWith(934, { document_type_id: 60 }));
  });

  it('createTagThenAdd keeps a tag added since render by reading the cached document', async () => {
    const tagMutate = vi.fn(
      (name: string, opts?: { onSuccess?: (data: TaxonomyItem) => void }) => {
        opts?.onSuccess?.({ id: 200, name, document_count: 0 });
      },
    );
    mockUseCreateTag.mockReturnValue(
      createMutationStub({ mutate: tagMutate as unknown as UseMutateFunction<TaxonomyItem, Error, string> }),
    );
    // An earlier create already landed: the cache is newer than the rendered prop.
    const queryClient = makeQueryClient();
    queryClient.setQueryData(['document', DOC.id], { ...DOC, tags: [...DOC.tags, 'new-tag'] });

    renderScreen({ role: 'member', queryClient });
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'alpha-tag' } });
    fireEvent.click(screen.getByRole('option', { name: /create/i }));

    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(1));
    expect(sentPatches()[0]).toEqual({ tags: [100, 101, 102, 103, 200] });
  });

  it('sends an edit made during a save once that save settles, merged with later edits', async () => {
    const first = deferred<LibraryDocument>();
    mockPatchDocument.mockReturnValueOnce(first.promise);
    renderScreen({ role: 'member' });

    renameTitle('Renamed');
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(1));

    // Two edits while the title save is in flight; the second correspondent wins.
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.click(screen.getByText('Revenue.ie'));
    fireEvent.click(screen.getByRole('button', { name: 'Payslip' }));
    fireEvent.click(screen.getByText('Invoice'));
    expect(mockPatchDocument).toHaveBeenCalledTimes(1);

    first.resolve(DOC);
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ correspondent_id: 2, document_type_id: 11 });
  });

  it('a tag edit made while another tag save is in flight keeps the first edit', async () => {
    const first = deferred<LibraryDocument>();
    mockPatchDocument.mockReturnValueOnce(first.promise);
    renderScreen({ role: 'member' });

    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByRole('option', { name: /new-tag/i }));
    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(1));

    first.resolve(DOC);
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ tags: [100, 102, 103] });
  });

  it('a tag edit after a save keeps the tag that save added, though the index still has the old tags', async () => {
    renderScreen({ role: 'member', live: true });

    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByRole('option', { name: /new-tag/i }));
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ tags: [100, 102, 103] });
  });

  it('a tag edit keeps a tag another change added while an earlier edit was pending', async () => {
    mockUseTags.mockReturnValue(queryOk([
      ...ALL_TAGS,
      { id: 104, name: 'medical', document_count: 1 },
      { id: 105, name: 'car', document_count: 1 },
    ]));
    // By the next read the index has the edit and a tag the pipeline added meanwhile.
    mockGetDocument.mockResolvedValue({ ...DOC, tags: [...DOC.tags, 'new-tag', 'medical'] });
    renderScreen({ role: 'member', live: true });

    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByRole('option', { name: /new-tag/i }));
    await waitFor(() => expect(mockGetDocument).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: /remove medical/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('option', { name: /car/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ tags: [100, 101, 102, 103, 104, 105] });
  });

  it('shows a title another change set after the user\'s rename', async () => {
    mockGetDocument.mockResolvedValue({ ...DOC, title: 'Set by someone else' });
    renderScreen({ role: 'member', live: true });
    renameTitle('Renamed');
    expect(await screen.findByRole('button', { name: 'Edit title: Set by someone else' })).toBeInTheDocument();
  });

  it('a tag removed and added back is kept when a read shows the state in between', async () => {
    const queryClient = makeQueryClient();
    renderScreen({ role: 'member', live: true, queryClient });

    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByRole('option', { name: /ireland/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();

    // The index catches up with the removal only.
    mockGetDocument.mockResolvedValue({ ...DOC, tags: ['2026', 'payroll'] });
    await act(() => queryClient.invalidateQueries({ queryKey: ['document', DOC.id] }));

    fireEvent.click(screen.getByRole('option', { name: /new-tag/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(3));
    expect(sentPatches()[2]).toEqual({ tags: [100, 102, 101, 103] });
  });

  it('keeps showing a saved title while the index still has the old one', async () => {
    renderScreen({ role: 'member', live: true });
    renameTitle('Renamed');
    expect(await screen.findByText(/^saved$/i)).toBeInTheDocument();
    await waitFor(() => expect(mockGetDocument).toHaveBeenCalledTimes(2));
    expect(screen.getByRole('button', { name: 'Edit title: Renamed' })).toBeInTheDocument();
  });

  it('a tag edit made while a retry is in flight keeps the tag being retried', async () => {
    const retry = deferred<LibraryDocument>();
    mockPatchDocument.mockRejectedValueOnce(new Error('network down')).mockReturnValueOnce(retry.promise);
    renderScreen({ role: 'member' });

    fireEvent.click(screen.getByRole('button', { name: /add tag/i }));
    fireEvent.click(screen.getByRole('option', { name: /new-tag/i }));
    fireEvent.click(await screen.findByRole('button', { name: /couldn't save/i }));
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole('button', { name: /remove ireland/i }));
    retry.resolve(DOC);
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(3));
    expect(sentPatches()[2]).toEqual({ tags: [100, 102, 103] });
  });

  it('an edit made after a failed save is sent together with the failed change', async () => {
    mockPatchDocument.mockRejectedValueOnce(new Error('network down'));
    renderScreen({ role: 'member' });

    renameTitle('Renamed');
    await screen.findByRole('button', { name: /couldn't save/i });
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.click(screen.getByText('Revenue.ie'));

    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ title: 'Renamed', correspondent_id: 2 });
  });

  it('sends an edit queued behind a save after the user has left the page', async () => {
    const first = deferred<LibraryDocument>();
    mockPatchDocument.mockReturnValueOnce(first.promise);
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <MemoryRouter initialEntries={['/document/934']}>
          <Routes>
            <Route
              path="/document/934"
              element={<DocumentScreen document={DOC} parent="library" parentSearch="" role="member" />}
            />
            <Route path="/library" element={<p>library page</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    renameTitle('Renamed');
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'eBay' }));
    fireEvent.click(screen.getByText('Revenue.ie'));
    fireEvent.click(screen.getByRole('link', { name: /library/i }));
    expect(await screen.findByText('library page')).toBeInTheDocument();

    first.resolve(DOC);
    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ correspondent_id: 2 });
  });

  it('retry button re-sends the failed PATCH', async () => {
    mockPatchDocument.mockRejectedValueOnce(new Error('network down'));
    renderScreen({ role: 'member' });

    renameTitle('Renamed');
    fireEvent.click(await screen.findByRole('button', { name: /couldn't save/i }));

    await waitFor(() => expect(mockPatchDocument).toHaveBeenCalledTimes(2));
    expect(sentPatches()[1]).toEqual({ title: 'Renamed' });
  });
});
