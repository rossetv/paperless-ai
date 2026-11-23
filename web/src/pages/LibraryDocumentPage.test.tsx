import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LibraryDocumentPage } from './LibraryDocumentPage';
import { ApiError } from '../api/client';
import * as client from '../api/client';

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/library/document/:id" element={<LibraryDocumentPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return utils;
}

describe('LibraryDocumentPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches the document by id and renders the document title', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 42,
      title: 'An invoice',
      correspondent: 'ACME',
      document_type: 'Invoice',
      created: '2024-03-01T00:00:00Z',
      tags: ['urgent'],
      page_count: 3,
      paperless_url: 'https://paperless.test/documents/42/',
    });
    renderAt('/library/document/42');
    await waitFor(() => expect(screen.getByText('An invoice')).toBeInTheDocument());
    expect(client.getDocument).toHaveBeenCalledWith(42);
  });

  it('renders the document title via DocumentScreen', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 7,
      title: 'Tax return 2025',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: 'https://paperless.test/documents/7/',
    });
    renderAt('/library/document/7');
    // The title may render as a heading (canEdit=false) or a button-headed h1
    // (canEdit=true, when useMe hasn't resolved). Either way the text is visible.
    await waitFor(() =>
      expect(screen.getByText('Tax return 2025')).toBeInTheDocument(),
    );
  });

  it('breadcrumb links to /library when no parent params', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 42,
      title: 'An invoice',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: 'https://paperless.test/documents/42/',
    });
    renderAt('/library/document/42');
    await waitFor(() => expect(screen.getByText('An invoice')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library');
  });

  it('breadcrumb preserves parent params', async () => {
    vi.spyOn(client, 'getDocument').mockResolvedValue({
      id: 42,
      title: 'An invoice',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: 'https://paperless.test/documents/42/',
    });
    renderAt('/library/document/42?tag=12&sort=title');
    await waitFor(() => expect(screen.getByText('An invoice')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute(
      'href',
      '/library?tag=12&sort=title',
    );
  });

  it('shows the loading state while the document is loading', () => {
    vi.spyOn(client, 'getDocument').mockReturnValue(new Promise(() => {}));
    renderAt('/library/document/42');
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('shows a "not found" empty state on 404', async () => {
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
    await Promise.resolve();
    expect(stub).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByText(/could not load document/i)).toBeInTheDocument(),
    );
  });

  it('opening another cached document does not carry over an unsaved edit', async () => {
    const doc = (id: number, title: string) => ({
      id,
      title,
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: `https://paperless.test/documents/${id}/`,
    });
    vi.spyOn(client, 'getDocument').mockImplementation(async (id: number) => doc(id, id === 42 ? 'First' : 'Second'));
    vi.spyOn(client, 'patchDocument').mockReturnValue(new Promise(() => {}));
    vi.spyOn(client, 'me').mockResolvedValue({
      user: {
        id: 1,
        username: 'm',
        display_name: null,
        email: null,
        role: 'member',
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        last_login_at: null,
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['document', 7], doc(7, 'Second'));
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library/document/42']}>
          <Routes>
            <Route
              path="/library/document/:id"
              element={
                <>
                  <LibraryDocumentPage />
                  <Link to="/library/document/7">next</Link>
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Edit title: First' }));
    const input = screen.getByDisplayValue('First');
    fireEvent.change(input, { target: { value: 'Renamed' } });
    fireEvent.blur(input);
    expect(screen.getByRole('button', { name: 'Edit title: Renamed' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: 'next' }));
    expect(await screen.findByRole('button', { name: 'Edit title: Second' })).toBeInTheDocument();
  });

  it('keeps the loaded document when a later refetch fails', async () => {
    const getDocument = vi.spyOn(client, 'getDocument').mockResolvedValueOnce({
      id: 42,
      title: 'Kept doc',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: 'https://paperless.test/documents/42/',
    });
    getDocument.mockRejectedValue(new ApiError(500, 'boom'));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/library/document/42']}>
          <Routes>
            <Route path="/library/document/:id" element={<LibraryDocumentPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await screen.findByText('Kept doc');
    await qc.invalidateQueries();
    await waitFor(() => expect(getDocument).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(qc.getQueryState(['document', 42])?.status).toBe('error'));
    expect(screen.getByText('Kept doc')).toBeInTheDocument();
    expect(screen.queryByText(/could not load document/i)).not.toBeInTheDocument();
  });

  it('shows the index-initialising screen with a retry on a 503', async () => {
    const getDocument = vi
      .spyOn(client, 'getDocument')
      .mockRejectedValueOnce(new ApiError(503, 'not ready'));
    getDocument.mockResolvedValue({
      id: 42,
      title: 'Ready doc',
      correspondent: null,
      document_type: null,
      created: null,
      tags: [],
      page_count: null,
      paperless_url: 'https://paperless.test/documents/42/',
    });
    renderAt('/library/document/42');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'The index is initialising.' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/could not load document/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry now' }));
    expect(await screen.findByText('Ready doc')).toBeInTheDocument();
  });
});
