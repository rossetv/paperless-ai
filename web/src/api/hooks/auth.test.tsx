import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useLogin } from './auth';
import { queryKeys } from './keys';

vi.mock('../client', () => ({
  login: vi.fn().mockResolvedValue({ user: { id: 2 } }),
  logout: vi.fn(),
  me: vi.fn(),
  setup: vi.fn(),
  setupStatus: vi.fn(),
  publicStats: vi.fn(),
}));

describe('useLogin', () => {
  it('drops every cached query of the earlier session but keeps the session check', async () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.me(), { user: { id: 1 } });
    qc.setQueryData(queryKeys.recentSearches(), [{ query: 'user one secret' }]);
    qc.setQueryData(queryKeys.apiKeys(), [{ id: 1 }]);
    qc.setQueryData(['search', 'kept'], { userId: 1 });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLogin(), { wrapper });
    result.current.mutate({ username: 'two', password: 'pw', remember: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(qc.getQueryData(queryKeys.recentSearches())).toBeUndefined();
    expect(qc.getQueryData(queryKeys.apiKeys())).toBeUndefined();
    expect(qc.getQueryData(['search', 'kept'])).toBeUndefined();
    expect(qc.getQueryState(queryKeys.me())).toBeDefined();
  });
});
