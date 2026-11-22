import { describe, it, expect, vi } from 'vitest';
import { ApiError, Unauthenticated, login, logout, setup as setupCall } from './api/client';
import { queryKeys } from './api/hooks/keys';
import { createQueryClient, shouldRetry } from './queryClient';

vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api/client')>()),
  login: vi.fn(() => Promise.reject(new Unauthenticated())),
  logout: vi.fn(() => Promise.reject(new Unauthenticated())),
  setup: vi.fn(() => Promise.reject(new Unauthenticated())),
}));

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

  describe('a 401', () => {
    function setup() {
      const client = createQueryClient();
      const invalidate = vi.spyOn(client, 'invalidateQueries');
      return { client, invalidate };
    }
    const meInvalidated = (invalidate: { mock: { calls: unknown[][] } }) =>
      invalidate.mock.calls.some(
        ([filter]) => JSON.stringify((filter as { queryKey: unknown }).queryKey) === JSON.stringify(queryKeys.me()),
      );

    it('from a page query re-checks the session', async () => {
      const { client, invalidate } = setup();
      await client
        .fetchQuery({ queryKey: ['documents'], queryFn: () => Promise.reject(new Unauthenticated()) })
        .catch(() => undefined);
      expect(meInvalidated(invalidate)).toBe(true);
    });

    it('from a mutation re-checks the session', async () => {
      const { client, invalidate } = setup();
      await client
        .getMutationCache()
        .build(client, { mutationFn: () => Promise.reject(new Unauthenticated()) })
        .execute(undefined)
        .catch(() => undefined);
      expect(meInvalidated(invalidate)).toBe(true);
    });

    it('from the session check itself does not loop', async () => {
      const { client, invalidate } = setup();
      await client
        .fetchQuery({ queryKey: queryKeys.me(), meta: { skipSessionCheck: true }, queryFn: () => Promise.reject(new Unauthenticated()) })
        .catch(() => undefined);
      expect(invalidate).not.toHaveBeenCalled();
    });

    it('from sign-in, sign-out or setup (a wrong password) is left alone', async () => {
      const { client, invalidate } = setup();
      for (const mutationFn of [login, logout, setupCall]) {
        await client
          .getMutationCache()
          .build(client, { mutationFn: mutationFn as () => Promise<unknown>, meta: { skipSessionCheck: true } })
          .execute(undefined)
          .catch(() => undefined);
      }
      expect(invalidate).not.toHaveBeenCalled();
    });

    it('from a wrapped mutation function is left alone when it carries the marker', async () => {
      const { client, invalidate } = setup();
      await client
        .getMutationCache()
        .build(client, { mutationFn: () => login({} as never), meta: { skipSessionCheck: true } })
        .execute(undefined)
        .catch(() => undefined);
      expect(invalidate).not.toHaveBeenCalled();
    });

    it('is ignored for other errors', async () => {
      const { client, invalidate } = setup();
      await client
        .fetchQuery({ queryKey: ['documents'], queryFn: () => Promise.reject(new ApiError(500)) })
        .catch(() => undefined);
      expect(invalidate).not.toHaveBeenCalled();
    });
  });
});
