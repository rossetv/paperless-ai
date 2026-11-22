/** Document hooks: single fetch, optimistic metadata patch, AI re-runs and deletion. */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  getDocument,
  patchDocument,
  reclassifyDocument,
  retranscribeDocument,
  deleteDocument,
} from '../client';
import type { LibraryDocument, DocumentPatch } from '../types';
import { queryKeys } from './keys';

/**
 * One document's metadata — GET /api/documents/{id}, for routes opened from a
 * shareable URL. Disabled while `documentId` is `null`.
 */
export function useDocument(
  documentId: number | null,
): UseQueryResult<LibraryDocument, Error> {
  return useQuery({
    queryKey: queryKeys.document(documentId ?? 0),
    queryFn: () => getDocument(documentId as number),
    enabled: documentId !== null,
    // A 404 (stale shared link) or 401 (expired session) won't change on retry.
    retry: false,
  });
}

/**
 * Partially update a document's metadata — PATCH /api/documents/{id}, optimistically.
 *
 * Title and date are merged into the cache at once and rolled back on error. The
 * PATCH response is not written to the cache: it carries pre-edit values until
 * the next reconcile and would revert the edit. Tags, correspondent and type are
 * ids in the patch but names on `LibraryDocument`, so they wait for the refetch.
 */
export function useUpdateDocument(): UseMutationResult<
  LibraryDocument,
  Error,
  { id: number; patch: DocumentPatch },
  { previous: LibraryDocument | undefined }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }) => patchDocument(id, patch),
    onMutate: async ({ id, patch }) => {
      await qc.cancelQueries({ queryKey: queryKeys.document(id) });
      const previous = qc.getQueryData<LibraryDocument>(queryKeys.document(id));
      if (previous !== undefined) {
        const optimistic: LibraryDocument = { ...previous };
        if ('title' in patch) optimistic.title = patch.title ?? null;
        if ('document_date' in patch) optimistic.created = patch.document_date ?? null;
        qc.setQueryData(queryKeys.document(id), optimistic);
      }
      return { previous };
    },
    onError: (_err, vars, context) => {
      if (context?.previous !== undefined) {
        qc.setQueryData(queryKeys.document(vars.id), context.previous);
      }
    },
    onSettled: (_data, _err, vars) => {
      void qc.invalidateQueries({ queryKey: queryKeys.document(vars.id) });
      void qc.invalidateQueries({ queryKey: ['documents'] });
      void qc.invalidateQueries({ queryKey: ['search'] });
      void qc.invalidateQueries({ queryKey: queryKeys.facets() });
      void qc.invalidateQueries({ queryKey: queryKeys.stats() });
    },
  });
}

/**
 * Queue AI re-classification — POST /api/documents/{id}/reclassify.
 *
 * No invalidation: the new title and type arrive with the next reconcile cycle.
 */
export function useReclassifyDocument(): UseMutationResult<void, Error, number> {
  return useMutation({ mutationFn: reclassifyDocument });
}

/**
 * Queue AI re-transcription (OCR) — POST /api/documents/{id}/retranscribe.
 *
 * No invalidation: the new content arrives with the next reconcile cycle.
 */
export function useRetranscribeDocument(): UseMutationResult<void, Error, number> {
  return useMutation({ mutationFn: retranscribeDocument });
}

/**
 * Permanently delete a document — DELETE /api/documents/{id}. Admin-only.
 *
 * Drops the document's cache entry (so back-navigation shows no ghost) and
 * invalidates the library list and search results. The caller navigates away.
 */
export function useDeleteDocument(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: ['document', id] });
      void qc.invalidateQueries({ queryKey: ['documents'] });
      void qc.invalidateQueries({ queryKey: ['search'] });
      void qc.invalidateQueries({ queryKey: queryKeys.facets() });
      void qc.invalidateQueries({ queryKey: queryKeys.stats() });
    },
  });
}
