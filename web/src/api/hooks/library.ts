/**
 * Library and document-editing query and mutation hooks — Wave 7/8/9.
 *
 * Covers the single-document fetch (shareable URLs), optimistic metadata patch,
 * AI re-classification / re-transcription, and permanent deletion.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

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
 * `useQuery` for one document's metadata — GET /api/documents/{id}.
 *
 * Used by the document-preview route components that mount from a shareable
 * URL (`/document/:id`, `/library/document/:id`) when there is no cached
 * library list to read from. The query is disabled when `documentId` is
 * `null` (e.g. whilst the route param is being parsed).
 */
export function useDocument(
  documentId: number | null,
): UseQueryResult<LibraryDocument, Error> {
  return useQuery({
    queryKey: queryKeys.document(documentId ?? 0),
    queryFn: () => getDocument(documentId as number),
    enabled: documentId !== null,
    // A 404 (stale shared link) or 401 (expired session) is deterministic —
    // retrying just doubles the round-trip before the page renders the
    // error state. Matches the convention used by sibling error-prone hooks.
    retry: false,
  });
}

/**
 * Partially update a document's metadata — PATCH /api/documents/{id}.
 *
 * Uses optimistic UI: on mutation start the cache is updated immediately with
 * the fields we can merge directly (title, created). On error the snapshot is
 * rolled back. On settle (success or error) the cache entry is invalidated so
 * a background refetch picks up the reconciled server state.
 *
 * The server response is NOT written directly into the cache in `onSuccess`
 * because Paperless-ngx has a reconcile lag — the PATCH response still carries
 * pre-edit values until the next indexer cycle. Writing it would visibly revert
 * the user's edit immediately after a successful save.
 *
 * `tags`, `correspondent_id`, and `document_type_id` are id-based in the patch
 * but name-based on `LibraryDocument`, so they cannot be merged optimistically
 * without a full taxonomy look-up. The invalidation in `onSettled` handles them
 * once the reconcile cycle completes.
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
    },
  });
}

/**
 * Trigger AI re-classification for a document — POST /api/documents/{id}/reclassify.
 *
 * One-shot fire-and-forget: queues a backend job and resolves. Carries no
 * cache invalidation — the document title/type will update on the next
 * reconcile cycle. Throws `Unauthenticated` on 401 and `ApiError` on 403+.
 */
export function useReclassifyDocument(): UseMutationResult<void, Error, number> {
  return useMutation({ mutationFn: reclassifyDocument });
}

/**
 * Trigger AI re-transcription (OCR) for a document — POST /api/documents/{id}/retranscribe.
 *
 * One-shot fire-and-forget: queues a backend job and resolves. No cache
 * invalidation needed — content updates arrive on the next reconcile cycle.
 */
export function useRetranscribeDocument(): UseMutationResult<void, Error, number> {
  return useMutation({ mutationFn: retranscribeDocument });
}

/**
 * Permanently delete a document — DELETE /api/documents/{id}.
 *
 * Admin-only. On success:
 * - Removes the `['document', id]` cache entry so a stale back-navigation
 *   does not show a ghost document.
 * - Invalidates `['documents']` so the library list reflects the deletion.
 * - Invalidates `['search']` so cached search results no longer include the
 *   deleted document.
 *
 * The calling component is responsible for navigating away after onSuccess.
 */
export function useDeleteDocument(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteDocument,
    onSuccess: (_, id) => {
      qc.removeQueries({ queryKey: ['document', id] });
      void qc.invalidateQueries({ queryKey: ['documents'] });
      void qc.invalidateQueries({ queryKey: ['search'] });
    },
  });
}
