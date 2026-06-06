/**
 * Unit tests for `useDebounce`.
 *
 * Uses Vitest's fake-timer API so tests run synchronously without real delays.
 */

import { renderHook, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { useDebounce } from './useDebounce';

describe('useDebounce', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns the initial value immediately', () => {
    const { result } = renderHook(() => useDebounce('hello', 300));
    expect(result.current).toBe('hello');
  });

  it('does not update before the delay has elapsed', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'hello' } },
    );

    rerender({ value: 'world' });
    // 299 ms — still the old value
    act(() => { vi.advanceTimersByTime(299); });
    expect(result.current).toBe('hello');
  });

  it('updates after the delay has elapsed', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'hello' } },
    );

    rerender({ value: 'world' });
    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current).toBe('world');
  });

  it('resets the timer on each new value change', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: string }) => useDebounce(value, 300),
      { initialProps: { value: 'a' } },
    );

    rerender({ value: 'b' });
    act(() => { vi.advanceTimersByTime(200); }); // only 200 ms since last change
    rerender({ value: 'c' });
    act(() => { vi.advanceTimersByTime(200); }); // 200 ms since "c" — not yet debounced
    expect(result.current).toBe('a');

    act(() => { vi.advanceTimersByTime(100); }); // total 300 ms since "c"
    expect(result.current).toBe('c');
  });

  it('works with number values', () => {
    const { result, rerender } = renderHook(
      ({ value }: { value: number }) => useDebounce(value, 500),
      { initialProps: { value: 0 } },
    );

    rerender({ value: 42 });
    act(() => { vi.advanceTimersByTime(500); });
    expect(result.current).toBe(42);
  });
});
