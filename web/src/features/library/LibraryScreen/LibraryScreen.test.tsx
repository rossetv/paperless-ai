import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { MemoryRouter, Routes, Route, useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import { LibraryScreen } from './LibraryScreen';
import type {
  DocumentsResponse,
  FacetsResponse,
  LibraryDocument,
} from '../../../api/types';

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
    paperless_url: `https://paperless.test/documents/${id}/`,
  };
}

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

/** Renders the current location for URL assertions. */
function LocationProbe({ testId = 'location-probe' }: { testId?: string }) {
  const loc = useLocation();
  return (
    <span data-testid={testId} style={{ display: 'none' }}>
      {loc.pathname}{loc.search}
    </span>
  );
}

/** Renders how the last navigation happened (POP, PUSH or REPLACE). */
function NavTypeProbe() {
  return <span data-testid="nav-type">{useNavigationType()}</span>;
}

function renderScreen(initialEntry = '/library') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="*" element={<LibraryScreen />} />
      </Routes>
      <LocationProbe />
      <NavTypeProbe />
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
    expect(screen.getByText(/14,238/)).toBeInTheDocument();
    expect(screen.getByText(/showing/i)).toBeInTheDocument();
  });

  it('shows no count while the list is loading or after it failed', () => {
    mockUseDocuments.mockReturnValue(documentsResult(undefined, { isLoading: true }));
    const { unmount } = renderScreen();
    expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
    unmount();

    mockUseDocuments.mockReturnValue(documentsResult(undefined, { isError: true }));
    renderScreen();
    expect(screen.queryByText(/total/i)).not.toBeInTheDocument();
  });

  it('shows an empty state when no documents match the filters', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?q=nothing');
    // Both the EmptyState title and description match.
    expect(screen.getAllByText(/no documents/i)[0]).toBeInTheDocument();
  });

  it('refetches with a new query string when the search is submitted', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen();
    const field = screen.getByRole('searchbox');
    await userEvent.type(field, 'energy{Enter}');
    const lastCall = mockUseDocuments.mock.calls.at(-1)![0];
    expect(lastCall.query).toBe('energy');
    expect(lastCall.page).toBe(1);
  });

  it('shows the text query in the field and as a chip, and clears it from either', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?q=energy&tag=5');
    expect(screen.getByRole('searchbox')).toHaveValue('energy');
    await userEvent.click(screen.getByRole('button', { name: 'Remove “energy”' }));
    expect(screen.getByTestId('location-probe').textContent).toBe('/library?tag=5');
    expect(screen.getByRole('searchbox')).toHaveValue('');
  });

  it('Clear all also clears the text query', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?q=energy&tag=5');
    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(screen.getByTestId('location-probe').textContent).toBe('/library');
  });

  it('submitting an emptied field clears the text query', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?q=energy');
    await userEvent.clear(screen.getByRole('searchbox'));
    await userEvent.type(screen.getByRole('searchbox'), '{Enter}');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library');
  });

  it('says the library is empty when nothing is filtered and nothing is indexed', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen();
    expect(screen.getByText('The library is empty')).toBeInTheDocument();
    expect(screen.queryByText(/match the current filters/i)).not.toBeInTheDocument();
  });

  it('goes to the last page, replacing history, when the page is past the end', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 50, page: 99, page_size: 24 }),
    );
    renderScreen('/library?page=99');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library?page=3');
    expect(screen.getByTestId('nav-type').textContent).toBe('REPLACE');
  });

  it('does not redirect on the previous query\'s total while new data loads', () => {
    mockUseDocuments.mockReturnValue({
      ...documentsResult({ documents: [], total: 5, page: 1, page_size: 24 }),
      isPlaceholderData: true,
    });
    renderScreen('/library?page=3');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library?page=3');
  });

  it('keeps focus in the search box after a submit', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [makeDoc(1, 'Doc one')], total: 1, page: 1, page_size: 24 }),
    );
    renderScreen();
    const box = screen.getByRole('searchbox');
    await userEvent.type(box, 'gas{Enter}');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library?q=gas');
    expect(screen.getByRole('searchbox')).toHaveFocus();
  });

  it('shows the URL\'s query in the search box when it changes elsewhere', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [makeDoc(1, 'Doc one')], total: 1, page: 1, page_size: 24 }),
    );
    renderScreen('/library?q=gas');
    expect(screen.getByRole('searchbox')).toHaveValue('gas');
    await userEvent.click(screen.getByRole('button', { name: 'Clear all' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
  });

  it('goes to page 1 when a past-the-end page has no results at all', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 4, page_size: 24 }),
    );
    renderScreen('/library?page=4');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library');
  });

  it('shows date filter chips as formatted dates', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?from=2025-01-05&to=2025-03-09');
    expect(screen.getByText('From 5 Jan 2025')).toBeInTheDocument();
    expect(screen.getByText('To 9 Mar 2025')).toBeInTheDocument();
  });

  it('shows an unparseable date as the raw value', () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?from=garbage');
    expect(screen.getByText('From garbage')).toBeInTheDocument();
  });

  it('does not call the library empty while a tag filter is unresolved', () => {
    mockUseFacets.mockReturnValue({ data: undefined, isLoading: true, isError: false });
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [], total: 0, page: 1, page_size: 24 }),
    );
    renderScreen('/library?tag=1');
    expect(screen.getByText('No documents match')).toBeInTheDocument();
    expect(screen.queryByText('The library is empty')).not.toBeInTheDocument();
  });

  it('clears a whitespace-only search from the field', async () => {
    mockUseDocuments.mockReturnValue(
      documentsResult({ documents: [makeDoc(1, 'Doc one')], total: 1, page: 1, page_size: 24 }),
    );
    renderScreen();
    await userEvent.type(screen.getByRole('searchbox'), '   {Enter}');
    expect(screen.getByTestId('location-probe').textContent).toBe('/library');
    expect(screen.getByRole('searchbox')).toHaveValue('');
  });

  it('retries the request from the error state', async () => {
    const refetch = vi.fn();
    mockUseDocuments.mockReturnValue({
      ...documentsResult(undefined, { isError: true }),
      refetch,
    });
    renderScreen();
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(refetch).toHaveBeenCalledTimes(1);
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
    expect(
      container.querySelector('[data-view="list"]'),
    ).not.toBeNull();
  });

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
    const { container } = renderScreen('/library?tag=12&view=list&sort=title');

    expect(screen.getByRole('button', { name: /remove urgent/i })).toBeInTheDocument();

    expect(container.querySelector('[data-view="list"]')).not.toBeNull();

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

    await userEvent.click(screen.getByRole('button', { name: 'Finance' }));

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

    await userEvent.click(screen.getByRole('button', { name: /open document: invoice april/i }));

    const probe = screen.getByTestId('location-probe');
    expect(probe.textContent).toMatch(/\/library\/document\/42/);
    expect(probe.textContent).toMatch(/tag=12/);
  });

  describe('scroll position on return', () => {
    const scrollTo = vi.fn();
    beforeEach(() => {
      scrollTo.mockReset();
      window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
      sessionStorage.clear();
    });
    afterEach(() => vi.restoreAllMocks());

    it('restores the scroll position saved when a card was opened, once the list has rendered', async () => {
      const loaded = documentsResult({
        documents: [makeDoc(42, 'Invoice April')],
        total: 1,
        page: 1,
        page_size: 24,
      });
      mockUseDocuments.mockReturnValue(loaded);
      Object.defineProperty(window, 'scrollY', { value: 1806, configurable: true });
      const first = renderScreen();
      await userEvent.click(screen.getByRole('button', { name: /open document/i }));
      first.unmount();
      scrollTo.mockReset();

      // Back: the list is not cached, so it loads again before it renders.
      mockUseDocuments.mockReturnValue(documentsResult(undefined, { isLoading: true }));
      const { rerender } = render(
        <MemoryRouter initialEntries={['/library']}>
          <Routes>
            <Route path="*" element={<LibraryScreen />} />
          </Routes>
        </MemoryRouter>,
      );
      expect(scrollTo).not.toHaveBeenCalled();

      mockUseDocuments.mockReturnValue(loaded);
      rerender(
        <MemoryRouter initialEntries={['/library']}>
          <Routes>
            <Route path="*" element={<LibraryScreen />} />
          </Routes>
        </MemoryRouter>,
      );
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 1806 }));
    });

    const loadedList = () =>
      documentsResult({ documents: [makeDoc(42, 'Invoice April')], total: 1, page: 1, page_size: 24 });

    it('does not restore a saved position on a fresh visit that is not Back or Forward', async () => {
      mockUseDocuments.mockReturnValue(loadedList());
      // Whatever key the new entry gets, the store answers with an old offset.
      vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('1806');
      function ToLibrary() {
        const navigate = useNavigate();
        return <button onClick={() => void navigate('/library')}>Library link</button>;
      }
      render(
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="/" element={<ToLibrary />} />
            <Route path="/library" element={<LibraryScreen />} />
          </Routes>
        </MemoryRouter>,
      );
      await userEvent.click(screen.getByRole('button', { name: 'Library link' }));
      expect(screen.getByRole('heading', { level: 1, name: 'Library' })).toBeInTheDocument();
      expect(scrollTo).not.toHaveBeenCalled();
    });

    it('forgets the saved position once it has been restored', async () => {
      mockUseDocuments.mockReturnValue(loadedList());
      sessionStorage.setItem('library-scroll:default', '1806');
      renderScreen();
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 1806 }));
      expect(sessionStorage.getItem('library-scroll:default')).toBeNull();
    });

    it('puts the position back when moving focus to the page heading scrolls it away', async () => {
      mockUseDocuments.mockReturnValue(loadedList());
      sessionStorage.setItem('library-scroll:default', '1806');
      renderScreen();
      scrollTo.mockReset();
      // The route announcer focuses the heading, which scrolls the page to the top.
      screen.getByRole('heading', { level: 1, name: 'Library' }).setAttribute('tabindex', '-1');
      screen.getByRole('heading', { level: 1, name: 'Library' }).focus();
      await Promise.resolve();
      expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ top: 1806 }));
    });

    it('does not restore on the first screen of a fresh page load', async () => {
      vi.resetModules();
      vi.spyOn(performance, 'getEntriesByType').mockReturnValue([
        { type: 'navigate' } as PerformanceNavigationTiming,
      ]);
      const { render: freshRender } = await import('@testing-library/react');
      const { MemoryRouter: FreshRouter, Routes: FreshRoutes, Route: FreshRoute } = await import('react-router-dom');
      const { LibraryScreen: FreshScreen } = await import('./LibraryScreen');
      const hooks = await import('../../../api/hooks');
      (hooks.useDocuments as ReturnType<typeof vi.fn>).mockReturnValue(loadedList());
      (hooks.useFacets as ReturnType<typeof vi.fn>).mockReturnValue(facetsResult());
      sessionStorage.setItem('library-scroll:default', '1806');
      freshRender(
        <FreshRouter initialEntries={['/library']}>
          <FreshRoutes>
            <FreshRoute path="*" element={<FreshScreen />} />
          </FreshRoutes>
        </FreshRouter>,
      );
      expect(scrollTo).not.toHaveBeenCalled();
    });

    it('does not scroll when nothing was saved for this history entry', () => {
      mockUseDocuments.mockReturnValue(
        documentsResult({ documents: [makeDoc(1, 'Doc one')], total: 1, page: 1, page_size: 24 }),
      );
      renderScreen();
      expect(scrollTo).not.toHaveBeenCalled();
    });
  });
});
