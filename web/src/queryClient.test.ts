import { describe, it, expect } from 'vitest';
import { ApiError } from './api/client';
import { createQueryClient, shouldRetry } from './queryClient';

describe('shouldRetry', () => {
  it('does not retry a 4xx ApiError', () => {
    expect(shouldRetry(0, new ApiError(400))).toBe(false);
    expect(shouldRetry(0, new ApiError(422))).toBe(false);
  });

  it('retries a 5xx ApiError and a network error once', () => {
    expect(shouldRetry(0, new ApiError(503))).toBe(true);
    expect(shouldRetry(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetry(1, new ApiError(503))).toBe(false);
  });
});

describe('createQueryClient', () => {
  it('wires shouldRetry into the query defaults', () => {
    expect(createQueryClient().getDefaultOptions().queries?.retry).toBe(shouldRetry);
  });
});
