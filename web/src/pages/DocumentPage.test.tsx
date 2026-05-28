import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DocumentPage } from './DocumentPage';
import { ApiError } from '../api/client';
import * as client from '../api/client';

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let location = '';
  function Probe(): null {
    const loc = useLocation();
    location = loc.pathname + loc.search;
    return null;
  }
  const utils = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/document/:id" element={<DocumentPage />} />
          <Route path="*" element={<Probe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, getLocation: () => location };
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
  });
}

describe('DocumentPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches the document by id and renders the preview', async () => {
    stubDoc();
    renderAt('/document/42');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    expect(client.getDocument).toHaveBeenCalledWith(42);
  });

  it('close navigates to /library when the URL has no q param', async () => {
    stubDoc();
    const { getLocation } = renderAt('/document/42');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /close document preview/i }));
    await waitFor(() => expect(getLocation()).toBe('/library'));
  });

  it('close navigates to /?<params> when the URL has a q param', async () => {
    stubDoc();
    const { getLocation } = renderAt('/document/42?q=invoice&tag=5');
    await waitFor(() => expect(screen.getByText('A doc')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /close document preview/i }));
    await waitFor(() => expect(getLocation()).toBe('/?q=invoice&tag=5'));
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
