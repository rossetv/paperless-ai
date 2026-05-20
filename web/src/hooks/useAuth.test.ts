/**
 * Tests for the useAuth hook and AuthProvider.
 *
 * Verifies that:
 * - initial state is unauthenticated
 * - login() toggles authenticated to true
 * - logout() resets authenticated to false
 */

import { renderHook, act } from '@testing-library/react';
import React from 'react';
import { useAuth, AuthProvider } from './useAuth';

describe('useAuth', () => {
  it('starts unauthenticated', () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(AuthProvider, null, children),
    });

    expect(result.current.authenticated).toBe(false);
  });

  it('login() sets authenticated to true', () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(AuthProvider, null, children),
    });

    act(() => {
      result.current.login();
    });

    expect(result.current.authenticated).toBe(true);
  });

  it('logout() resets authenticated to false after login', () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: ({ children }: { children: React.ReactNode }) =>
        React.createElement(AuthProvider, null, children),
    });

    act(() => {
      result.current.login();
    });

    expect(result.current.authenticated).toBe(true);

    act(() => {
      result.current.logout();
    });

    expect(result.current.authenticated).toBe(false);
  });

  it('throws when used outside AuthProvider', () => {
    // Suppress the expected console.error from React
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    expect(() => renderHook(() => useAuth())).toThrow(
      'useAuth must be used inside AuthProvider',
    );

    consoleError.mockRestore();
  });
});
