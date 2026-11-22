import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useUpdateDocument, useDeleteDocument } from './library';
import { queryKeys } from './keys';

vi.mock('../client', () => ({
  getDocument: vi.fn(),
  patchDocument: vi.fn().mockResolvedValue({}),
  reclassifyDocument: vi.fn(),
  retranscribeDocument: vi.fn(),
  deleteDocument: vi.fn().mockResolvedValue(undefined),
}));

function setup() {
  const qc = new QueryClient();
  const spy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const invalidated = () => spy.mock.calls.map((c) => c[0]?.queryKey);
  return { wrapper, invalidated };
}

describe('document mutations refresh the counts', () => {
  beforeEach(() => vi.clearAllMocks());

  it('updating a document invalidates facets and stats', async () => {
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useUpdateDocument(), { wrapper });
    result.current.mutate({ id: 1, patch: { title: 'x' } });
    await waitFor(() => expect(invalidated()).toContainEqual(queryKeys.facets()));
    expect(invalidated()).toContainEqual(queryKeys.stats());
  });

  it('deleting a document invalidates facets and stats', async () => {
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useDeleteDocument(), { wrapper });
    result.current.mutate(1);
    await waitFor(() => expect(invalidated()).toContainEqual(queryKeys.facets()));
    expect(invalidated()).toContainEqual(queryKeys.stats());
  });
});
