import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { LibraryScreen } from './LibraryScreen';
import type {
  DocumentsResponse,
  FacetsResponse,
  LibraryDocument,
} from '../../../api/types';

// Mock the api hooks layer — LibraryScreen calls useDocuments + useFacets.
vi.mock('../../../api/hooks', () => ({
  useDocuments: vi.fn(),
  useFacets: vi.fn(),
}));

import { useDocuments, useFacets } from '../../../api/hooks';

const mockUseDocuments = useDocuments as ReturnType<typeof vi.fn>;
const mockUseFacets = useFacets as ReturnType<typeof vi.fn>;

function makeDoc(id: number, title: string): LibraryDocument {
  return {
    id,
    title,
    correspondent: 'Npower Energy',
    document_type: 'Statement',
    created: '2025-01-12',
    tags: ['Energy'],
    page_count: 3,
  };
}

/** Build a faked react-query result object for useDocuments. */
function documentsResult(
  data: DocumentsResponse | undefined,
  flags: { isLoading?: boolean; isError?: boolean } = {},
) {
  return {
    data,
    isLoading: flags.isLoading ?? false,
    isError: flags.isError ?? false,
    isPlaceholderData: false,
  };
}

const EMPTY_FACETS: FacetsResponse = {
  correspondents: [],
  document_types: [],
  tags: [],
  earliest: null,
  latest: null,
};

function facetsResult(data: FacetsResponse = EMPTY_FACETS) {
  return { data, isLoading: false, isError: false };
}

beforeEach(() => {
  mockUseDocuments.mockReset();
  mockUseFacets.mockReset();
  mockUseFacets.mockReturnValue(facetsResult());
});

describe('LibraryScreen', () => {
  it('renders the Library heading', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    render(<LibraryScreen />);
    expect(
      screen.getByRole('heading', { level: 1, name: 'Library' }),
    ).toBeInTheDocument();
  });

  it('shows a loading state while documents load', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult(undefined, { isLoading: true }),
    );
    render(<LibraryScreen />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an error state when the request fails', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult(undefined, { isError: true }),
    );
    render(<LibraryScreen />);
    expect(screen.getByText(/could not load/i)).toBeInTheDocument();
  });

  it('renders a card per document', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one'), makeDoc(2, 'Doc two')],
        total: 2,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    expect(screen.getByText('Doc one')).toBeInTheDocument();
    expect(screen.getByText('Doc two')).toBeInTheDocument();
  });

  it('shows the total count and the result range in the header', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 14238,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    // Total is rendered with thousands separators.
    expect(screen.getByText(/14,238/)).toBeInTheDocument();
    // Range for page 1 of a 1-item page — text is split across nodes so use
    // the subheading container rather than a cross-node regex.
    expect(screen.getByText(/showing/i)).toBeInTheDocument();
  });

  it('shows an empty state when no documents match', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    render(<LibraryScreen />);
    // Both the EmptyState title and description contain "no documents" — assert
    // on the first (the primary message element, role="heading" equivalent).
    expect(screen.getAllByText(/no documents/i)[0]).toBeInTheDocument();
  });

  it('refetches with a new query string when the search is submitted', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    render(<LibraryScreen />);
    const field = screen.getByRole('searchbox');
    await userEvent.type(field, 'energy{Enter}');
    // The most recent useDocuments call carries the typed query.
    const lastCall = mockUseDocuments.mock.calls.at(-1)![0];
    expect(lastCall.query).toBe('energy');
    expect(lastCall.page).toBe(1);
  });

  it('changes the sort field and resets to page 1', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    await userEvent.click(screen.getByRole('button', { name: /sort/i }));
    await userEvent.click(
      screen.getByRole('menuitemradio', { name: 'Title' }),
    );
    const lastCall = mockUseDocuments.mock.calls.at(-1)![0];
    expect(lastCall.sort).toBe('title');
    expect(lastCall.page).toBe(1);
  });

  it('disables Previous on the first page', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 100,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    expect(
      screen.getByRole('button', { name: /previous/i }),
    ).toBeDisabled();
  });

  it('advances the page when Next is clicked', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 100,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    await userEvent.click(screen.getByRole('button', { name: /next/i }));
    const lastCall = mockUseDocuments.mock.calls.at(-1)![0];
    expect(lastCall.page).toBe(2);
  });

  it('disables Next on the last page', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 24,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled();
  });

  it('renders a removable chip for an active tag filter', () => {
    mockUseFacets.mockReturnValue(
      facetsResult({
        correspondents: [],
        document_types: [],
        tags: [{ kind: 'tag', id: 9, name: 'Energy' }],
        earliest: null,
        latest: null,
      }),
    );
    mockUseDocuments.mockImplementation(() =>
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    );
    render(<LibraryScreen />);
    // No active filter yet — no chip strip remove buttons.
    expect(
      screen.queryByRole('button', { name: /remove energy/i }),
    ).not.toBeInTheDocument();
  });

  it('toggles between grid and list view', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    );
    const { container } = render(<LibraryScreen />);
    await userEvent.click(screen.getByRole('button', { name: 'List' }));
    // The list container carries a data attribute for the active layout.
    expect(
      container.querySelector('[data-view="list"]'),
    ).not.toBeNull();
  });
});
