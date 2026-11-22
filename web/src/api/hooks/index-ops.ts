/** Index-operations hooks: status, reconcile history, failed documents, rebuild, reconcile. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  getIndexStatus,
  getIndexActivity,
  getFailedDocuments,
  rebuildIndex,
  postReconcile,
} from '../client';
import type {
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  RebuildResponse,
} from '../types';
import { queryKeys } from './keys';

const INDEX_STATUS_POLL_MS = 5_000;

const INDEX_ACTIVITY_POLL_MS = 10_000;

/**
 * The live index status, polled every 5 s.
 *
 * `retry: false` so an expired session's 401 reaches `ProtectedRoute` at once
 * instead of being retried.
 */
export function useIndexStatus(): UseQueryResult<IndexStatusResponse, Error> {
  return useQuery({
    queryKey: queryKeys.indexStatus(),
    queryFn: getIndexStatus,
    refetchInterval: INDEX_STATUS_POLL_MS,
    retry: false,
  });
}

/** The recent reconcile history, polled every 10 s since it only changes per cycle. */
export function useIndexActivity(): UseQueryResult<IndexActivityResponse, Error> {
  return useQuery({
    queryKey: queryKeys.indexActivity(),
    queryFn: getIndexActivity,
    refetchInterval: INDEX_ACTIVITY_POLL_MS,
    retry: false,
  });
}

/** Documents that failed OCR, classification or indexing (not polled). */
export function useFailedDocuments(): UseQueryResult<IndexFailedResponse, Error> {
  return useQuery({
    queryKey: queryKeys.failedDocuments(),
    queryFn: getFailedDocuments,
    retry: false,
  });
}

/**
 * Rebuild the index from scratch — POST /api/index/rebuild. Destructive, admin-only.
 *
 * Invalidates status, activity and failed documents so the dashboard shows the rebuilding state at once.
 */
export function useRebuildIndex(): UseMutationResult<RebuildResponse, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: rebuildIndex,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexActivity() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.failedDocuments() });
    },
  });
}

/** Trigger an immediate reconcile cycle — POST /api/reconcile; refreshes status, activity and failed documents. */
export function useReconcile(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: postReconcile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexActivity() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.failedDocuments() });
    },
  });
}
