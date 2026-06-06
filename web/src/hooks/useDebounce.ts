/**
 * `useDebounce` — delay a rapidly-changing value until it has stopped changing
 * for `delay` milliseconds.
 *
 * The hook mirrors the raw value immediately on the first render, then only
 * propagates subsequent changes once `delay` ms have elapsed without another
 * change — the classic debounce pattern for search inputs.
 *
 * Tier: hooks/ — allowed deps: React only (CODE_GUIDELINES §12.3).
 */

import { useState, useEffect } from 'react';

/**
 * Return a debounced copy of `value` that only updates after `delay` ms of
 * inactivity.
 *
 * @param value - The rapidly-changing source value.
 * @param delay - Quiet period in milliseconds before the debounced value updates.
 * @returns The debounced value; initially equals `value` synchronously.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
