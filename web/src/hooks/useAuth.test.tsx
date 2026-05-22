/**
 * Tests for the useAuth hook.
 *
 * useAuth wraps the `useMe` react-query hook. These tests mock `useMe` so the
 * hook can be exercised without a QueryClient or network.
 */

import { renderHook } from '@testing-library/react';
import type { UseQueryResult } from '@tanstack/react-query';
import type { MeResponse } from '../api/types';
import { useAuth, AuthProvider } from './useAuth';

vi.mock('../api/hooks', () => ({
  useMe: vi.fn(),
}));

import { useMe } from '../api/hooks';
const mockUseMe = useMe as ReturnType<typeof vi.fn>;

const SAMPLE_USER = {
  id: 1,
  username: 'alex.morgan',
  display_name: 'Alex Morgan',
  email: 'alex@home.lan',
  role: 'admin' as const,
  status: 'active' as const,
  created_at: '2026-05-01T00:00:00Z',
  last_login_at: null,
};

/** Build a UseQueryResult stub in the requested shape. */
function meResult(
  overrides: Partial<UseQueryResult<MeResponse, Error>>,
): UseQueryResult<MeResponse, Error> {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
    isSuccess: false,
    isPending: false,
    ...overrides,
  } as UseQueryResult<MeResponse, Error>;
}

describe('useAuth', () => {
  it('reports loading while the me query is loading', () => {
    mockUseMe.mockReturnValue(meResult({ isLoading: true, isPending: true }));
    const { result } = renderHook(() => useAuth());
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
  });

  it('reports authenticated with the user when me resolves', () => {
    mockUseMe.mockReturnValue(
      meResult({ isSuccess: true, data: { user: SAMPLE_USER } }),
    );
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.user?.username).toBe('alex.morgan');
    expect(result.current.role).toBe('admin');
  });

  it('reports unauthenticated when me errors (401)', () => {
    mockUseMe.mockReturnValue(
      meResult({ isError: true, error: new Error('Unauthenticated') }),
    );
    const { result } = renderHook(() => useAuth());
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(result.current.role).toBeNull();
  });

  it('AuthProvider renders its children unchanged', () => {
    mockUseMe.mockReturnValue(meResult({ isError: true }));
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <AuthProvider>{children}</AuthProvider>
      ),
    });
    // Smoke: the hook still works inside the provider.
    expect(result.current.isAuthenticated).toBe(false);
  });
});
