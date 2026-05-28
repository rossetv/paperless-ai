import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
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
});
