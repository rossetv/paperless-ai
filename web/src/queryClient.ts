import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { ApiError, Unauthenticated, login, logout, setup } from './api/client';
import { queryKeys } from './api/hooks/keys';

/** One retry for network errors and 5xx; a 4xx or 401 would only fail the same way again. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof Unauthenticated || (error instanceof ApiError && error.status < 500)) {
    return false;
  }
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  // A 401 mid-page means the session lapsed: re-check `me` so ProtectedRoute sends the user to
  // sign-in. The `me` query itself and the sign-in/out calls (a wrong password is a 401 too) are exempt.
  const recheckSession = (error: unknown) => {
    if (error instanceof Unauthenticated) {
      void client.invalidateQueries({ queryKey: queryKeys.me() });
    }
  };
  const authCalls: unknown[] = [login, logout, setup];
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (JSON.stringify(query.queryKey) !== JSON.stringify(queryKeys.me())) recheckSession(error);
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (!authCalls.includes(mutation.options.mutationFn)) recheckSession(error);
      },
    }),
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
  return client;
}
