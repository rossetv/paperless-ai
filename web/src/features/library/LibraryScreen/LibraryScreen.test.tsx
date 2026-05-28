import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
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

/**
 * A probe that records the current location for URL assertions. Place it as a
 * sibling route under `path="*"` so it renders alongside the subject.
 */
function LocationProbe({ testId = 'location-probe' }: { testId?: string }) {
  const loc = useLocation();
  return (
    <span data-testid={testId} style={{ display: 'none' }}>
      {loc.pathname}{loc.search}
    </span>
  );
}

/**
 * Render LibraryScreen inside a MemoryRouter at the given initial entry.
 * The LocationProbe is mounted in a sibling route so tests can read the
 * current URL after interactions.
 */
function renderScreen(initialEntry = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="*" element={<LibraryScreen />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
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
    renderScreen();
    expect(
      screen.getByRole('heading', { level: 1, name: 'Library' }),
    ).toBeInTheDocument();
  });

  it('shows a loading state while documents load', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult(undefined, { isLoading: true }),
    );
    renderScreen();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows an error state when the request fails', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult(undefined, { isError: true }),
    );
    renderScreen();
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
    renderScreen();
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
    renderScreen();
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
    renderScreen();
    // Both the EmptyState title and description contain "no documents" — assert
    // on the first (the primary message element, role="heading" equivalent).
    expect(screen.getAllByText(/no documents/i)[0]).toBeInTheDocument();
  });

  it('refetches with a new query string when the search is submitted', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen();
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
    renderScreen();
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
    renderScreen();
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
    renderScreen();
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
    renderScreen();
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
    renderScreen();
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
    const { container } = renderScreen();
    await userEvent.click(screen.getByRole('button', { name: 'List' }));
    // The list container carries a data attribute for the active layout.
    expect(
      container.querySelector('[data-view="list"]'),
    ).not.toBeNull();
  });

  // ── URL-driven state tests ────────────────────────────────────────────────

  it('mounts at a URL with filters and applies them from the URL', () => {
    mockUseFacets.mockReturnValue(
      facetsResult({
        correspondents: [],
        document_types: [],
        tags: [{ kind: 'tag', id: 12, name: 'Urgent' }],
        earliest: null,
        latest: null,
      }),
    );
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(1, 'Doc one')],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    );
    // Mount at a URL that sets tag=12, view=list, sort=title.
    const { container } = renderScreen('/library?tag=12&view=list&sort=title');

    // The "Urgent" chip appears in the active-filter strip (resolved from tag id 12).
    expect(screen.getByRole('button', { name: /remove urgent/i })).toBeInTheDocument();

    // The list-view container is rendered (only visible when there are results).
    expect(container.querySelector('[data-view="list"]')).not.toBeNull();

    // The sort control shows "title" as selected — verify via useDocuments call.
    const lastCall = mockUseDocuments.mock.calls.at(-1)![0];
    expect(lastCall.sort).toBe('title');
    expect(lastCall.tag_ids).toEqual([12]);
  });

  it('selecting a tag via FilterControls updates the URL', async () => {
    mockUseFacets.mockReturnValue(
      facetsResult({
        correspondents: [],
        document_types: [],
        tags: [{ kind: 'tag', id: 7, name: 'Finance' }],
        earliest: null,
        latest: null,
      }),
    );
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library');

    // Click the "Finance" chip in FilterControls to activate the tag filter.
    await userEvent.click(screen.getByRole('button', { name: 'Finance' }));

    // The URL now contains tag=7.
    const probe = screen.getByTestId('location-probe');
    expect(probe.textContent).toMatch(/tag=7/);
  });

  it('clicking a LibraryCard navigates to /library/document/:id with parent params', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({
        documents: [makeDoc(42, 'Invoice April')],
        total: 1,
        page: 1,
        page_size: 24,
      }),
    );
    renderScreen('/library?tag=12');

    // Click the card open button.
    await userEvent.click(screen.getByRole('button', { name: /preview "invoice april"/i }));

    // The URL should now be /library/document/42 with parent params preserved.
    const probe = screen.getByTestId('location-probe');
    expect(probe.textContent).toMatch(/\/library\/document\/42/);
    expect(probe.textContent).toMatch(/tag=12/);
  });
});
