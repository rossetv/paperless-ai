import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useLogin, useMe } from './auth';
import { me } from '../client';
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

  it('keeps the setup status and public stats, which are not per-user', async () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.setupStatus(), { needed: false });
    qc.setQueryData(queryKeys.publicStats(), { document_count: 3 });
    qc.setQueryData(queryKeys.stats(), { userId: 1 });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => useLogin(), { wrapper });
    result.current.mutate({ username: 'two', password: 'pw', remember: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(qc.getQueryData(queryKeys.setupStatus())).toEqual({ needed: false });
    expect(qc.getQueryData(queryKeys.publicStats())).toEqual({ document_count: 3 });
    expect(qc.getQueryData(queryKeys.stats())).toBeUndefined();
  });

  it('shows the new user, not the lapsed one, when the re-check after sign-in fails', async () => {
    vi.mocked(me).mockRejectedValue(new Error('server error'));
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.me(), { user: { id: 1 } });
    // The lapse: the cached `me` of user one is now in an error state.
    await qc.fetchQuery({ queryKey: queryKeys.me(), queryFn: me, staleTime: 0 }).catch(() => undefined);
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(() => ({ login: useLogin(), me: useMe() }), { wrapper });
    result.current.login.mutate({ username: 'two', password: 'pw', remember: false });
    await waitFor(() => expect(result.current.login.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.me.isFetching).toBe(false));

    expect(result.current.me.data).toEqual({ user: { id: 2 } });
  });
});
