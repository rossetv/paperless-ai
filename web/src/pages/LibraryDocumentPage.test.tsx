import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LibraryDocumentPage } from './LibraryDocumentPage';
import { ApiError } from '../api/client';
import * as client from '../api/client';

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let location = '';
  function LocationProbe(): null {
    const loc = useLocation();
    location = loc.pathname + loc.search;
    return null;
  }
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/library/document/:id" element={<LibraryDocumentPage />} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, getLocation: () => location };
}

describe('LibraryDocumentPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches the document by id and renders the preview', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 42,
      title: 'An invoice',
      correspondent: 'ACME',
      document_type: 'Invoice',
      created: '2024-03-01T00:00:00Z',
      tags: ['urgent'],
      page_count: 3,
    });
    renderAt('/library/document/42');
    await waitFor(() => expect(screen.getByText('An invoice')).toBeInTheDocument());
    expect(client.getDocument).toHaveBeenCalledWith(42);
  });

  it('closing the preview navigates to /library with parent search string preserved', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 42,
      title: 'An invoice',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
    });
    const { getLocation } = renderAt('/library/document/42?tag=12&sort=title');
    await waitFor(() => expect(screen.getByText('An invoice')).toBeInTheDocument());
    // Close button aria-label is "Close document preview" (DocumentViewerChrome).
    fireEvent.click(screen.getByRole('button', { name: /close document preview/i }));
    await waitFor(() =>
      expect(getLocation()).toBe('/library?tag=12&sort=title'),
    );
  });

  it('shows the loading state while the document is loading', () => {
    vi.spyOn(client, 'getDocument').mockReturnValue(new Promise(() => {}));
    renderAt('/library/document/42');
    // Spinner uses role="status".
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows a "not found" empty state on 404', async () => {
    // ApiError constructor: (status: number, message?: string)
    vi.spyOn(client, 'getDocument').mockRejectedValue(
      new ApiError(404, 'not found'),
    );
    renderAt('/library/document/42');
    await waitFor(() =>
      expect(screen.getByText(/document not found/i)).toBeInTheDocument(),
    );
  });

  it('does not fire a request when the :id is not a positive integer', async () => {
    const stub = vi.spyOn(client, 'getDocument');
    renderAt('/library/document/abc');
    // Allow microtasks to settle without timing-out.
    await Promise.resolve();
    expect(stub).not.toHaveBeenCalled();
    // The page renders the generic error state (data is undefined and no error).
    await waitFor(() =>
      expect(screen.getByText(/could not load document/i)).toBeInTheDocument(),
    );
  });
});
