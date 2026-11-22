import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DocumentPage } from './DocumentPage';
import { ApiError } from '../api/client';
import * as client from '../api/client';

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/document/:id" element={<DocumentPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return utils;
}

function stubDoc(): void {
  vi.spyOn(client, 'getDocument').mockResolvedValue({
    id: 42,
    title: 'A doc',
    correspondent: null,
    document_type: null,
    created: null,
    tags: [],
    page_count: null,
    paperless_url: 'https://paperless.test/documents/42/',
  });
}

describe('DocumentPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches the document by id and renders the document title', async () => {
    stubDoc();
    renderAt('/document/42');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    expect(client.getDocument).toHaveBeenCalledWith(42);
  });

  it('breadcrumb links to /library when no q param', async () => {
    stubDoc();
    renderAt('/document/42');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /library/i })).toHaveAttribute('href', '/library');
  });

  it('breadcrumb links to /?q=… when q param present', async () => {
    stubDoc();
    renderAt('/document/42?q=invoice&tag=5');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    expect(screen.getByRole('link', { name: /search results/i })).toHaveAttribute(
      'href',
      '/?q=invoice&tag=5',
    );
  });

  it('shows a "not found" empty state on 404', async () => {
    vi.spyOn(client, 'getDocument').mockRejectedValue(new ApiError(404, 'not found'));
    renderAt('/document/42');
    await waitFor(() =>
      expect(screen.getByText(/document not found/i)).toBeInTheDocument(),
    );
  });

  it('does not fire a request when the :id is not a positive integer', async () => {
    const stub = vi.spyOn(client, 'getDocument');
    renderAt('/document/abc');
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
        <MemoryRouter initialEntries={['/document/42']}>
          <Routes>
            <Route
              path="/document/:id"
              element={
                <>
                  <DocumentPage />
                  <Link to="/document/7">next</Link>
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
});
