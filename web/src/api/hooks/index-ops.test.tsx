import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useReconcile, useRebuildIndex } from './index-ops';
import { queryKeys } from './keys';

vi.mock('../client', () => ({
  getIndexStatus: vi.fn(),
  getIndexActivity: vi.fn(),
  getFailedDocuments: vi.fn(),
  rebuildIndex: vi.fn().mockResolvedValue({}),
  postReconcile: vi.fn().mockResolvedValue(undefined),
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

describe('index operations refresh the failed-documents list', () => {
  beforeEach(() => vi.clearAllMocks());

  it('a reconcile invalidates failed documents', async () => {
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useReconcile(), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(invalidated()).toContainEqual(queryKeys.failedDocuments()));
  });

  it('a rebuild invalidates failed documents', async () => {
    const { wrapper, invalidated } = setup();
    const { result } = renderHook(() => useRebuildIndex(), { wrapper });
    result.current.mutate();
    await waitFor(() => expect(invalidated()).toContainEqual(queryKeys.failedDocuments()));
  });
});
