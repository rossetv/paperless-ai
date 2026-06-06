/**
 * Index-operations query and mutation hooks — Wave 6.
 *
 * Daemon status, reconcile-activity history, failed documents, rebuild trigger,
 * and the manual-reconcile trigger.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

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

/** Poll interval for the live index status — 5 seconds. */
const INDEX_STATUS_POLL_MS = 5_000;

/** Poll interval for the reconcile-activity history — 10 seconds. */
const INDEX_ACTIVITY_POLL_MS = 10_000;

/**
 * The live index status — daemon statuses and index health.
 *
 * Polls every 5 s (`refetchInterval`) so the dashboard hero and daemon cards
 * stay current without a manual refresh. `retry: false` prevents
 * TanStack Query from hammering the server with retries when the session has
 * expired — a 401 should surface immediately to `ProtectedRoute`.
 */
export function useIndexStatus(): UseQueryResult<IndexStatusResponse, Error> {
  return useQuery({
    queryKey: queryKeys.indexStatus(),
    queryFn: getIndexStatus,
    refetchInterval: INDEX_STATUS_POLL_MS,
    retry: false,
  });
}

/**
 * The recent reconcile-activity history.
 *
 * Polls every 10 s — activity changes per reconcile cycle, which is coarser
 * than the second-to-second status. `retry: false` for the same reason as
 * `useIndexStatus`.
 */
export function useIndexActivity(): UseQueryResult<IndexActivityResponse, Error> {
  return useQuery({
    queryKey: queryKeys.indexActivity(),
    queryFn: getIndexActivity,
    refetchInterval: INDEX_ACTIVITY_POLL_MS,
    retry: false,
  });
}

/**
 * The list of documents that failed OCR / classification / indexing.
 *
 * Not polled — the list only changes when the indexer records a new failure.
 * `retry: false` prevents hammering on a 401.
 */
export function useFailedDocuments(): UseQueryResult<IndexFailedResponse, Error> {
  return useQuery({
    queryKey: queryKeys.failedDocuments(),
    queryFn: getFailedDocuments,
    retry: false,
  });
}

/**
 * Rebuild the index from scratch — POST /api/index/rebuild.
 *
 * DESTRUCTIVE and admin-only. On success the status and activity queries are
 * invalidated so the dashboard immediately reflects the index going into its
 * rebuilding state. Resolves with a `RebuildResponse` so the success toast
 * can surface the server's `detail` message.
 */
export function useRebuildIndex(): UseMutationResult<RebuildResponse, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: rebuildIndex,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexActivity() });
    },
  });
}

/**
 * Trigger an immediate reconcile cycle — POST /api/reconcile.
 *
 * On success the status and activity queries are invalidated so the new
 * cycle appears in the dashboard without waiting for the next poll tick.
 */
export function useReconcile(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: postReconcile,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.indexActivity() });
    },
  });
}
