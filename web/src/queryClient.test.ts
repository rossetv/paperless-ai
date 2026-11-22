import { describe, it, expect, vi } from 'vitest';
import { ApiError, Unauthenticated } from './api/client';
import { createQueryClient, shouldRetry } from './queryClient';

describe('shouldRetry', () => {
  it('does not retry a 4xx ApiError', () => {
    expect(shouldRetry(0, new ApiError(400))).toBe(false);
    expect(shouldRetry(0, new ApiError(422))).toBe(false);
  });

  it('does not retry a 401', () => {
    expect(shouldRetry(0, new Unauthenticated())).toBe(false);
  });

  it('retries a 5xx ApiError and a network error once', () => {
    expect(shouldRetry(0, new ApiError(503))).toBe(true);
    expect(shouldRetry(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetry(1, new ApiError(503))).toBe(false);
  });
});

describe('createQueryClient', () => {
  it('does not re-run a query that failed with a 404', async () => {
    const queryFn = vi.fn().mockRejectedValue(new ApiError(404));
    const client = createQueryClient();
    await client.fetchQuery({ queryKey: ['missing'], queryFn }).catch(() => undefined);
    expect(queryFn).toHaveBeenCalledTimes(1);
  });
});
