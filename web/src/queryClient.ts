import { QueryClient } from '@tanstack/react-query';
import { ApiError, Unauthenticated } from './api/client';

/** One retry for network errors and 5xx; a 4xx or 401 would only fail the same way again. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof Unauthenticated || (error instanceof ApiError && error.status < 500)) {
    return false;
  }
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        retry: shouldRetry,
        // The LLM-backed search is expensive; re-billing on every alt-tab is
        // wasteful. Auth hooks use staleTime:0 + mount refetch, so are unaffected.
        refetchOnWindowFocus: false,
      },
    },
  });
}
