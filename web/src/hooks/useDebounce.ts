import { useState, useEffect } from 'react';

/**
 * Return a debounced copy of `value` that only updates after `delay` ms of
 * inactivity. The first render returns `value` unchanged.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
