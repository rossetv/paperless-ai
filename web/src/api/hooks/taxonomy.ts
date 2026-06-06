/**
 * Taxonomy query and mutation hooks — correspondents, document types, tags.
 *
 * All three taxonomy lists are cached for 60 s and share the same
 * `TaxonomyItem` shape. Create mutations invalidate the relevant list so
 * pickers re-fetch the updated options.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  getCorrespondents,
  getDocumentTypes,
  getTags,
  createCorrespondent,
  createDocumentType,
  createTag,
} from '../client';
import type { TaxonomyItem } from '../types';
import { queryKeys } from './keys';

/**
 * All correspondents in Paperless-ngx — GET /api/correspondents.
 *
 * Cached for 60 s. Drives correspondent picker in the document edit panel.
 */
export function useCorrespondents(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.correspondents(),
    queryFn: getCorrespondents,
    staleTime: 60_000,
  });
}

/**
 * All document types in Paperless-ngx — GET /api/document-types.
 *
 * Cached for 60 s. Drives document-type picker in the document edit panel.
 */
export function useDocumentTypes(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.documentTypes(),
    queryFn: getDocumentTypes,
    staleTime: 60_000,
  });
}

/**
 * All tags in Paperless-ngx — GET /api/tags.
 *
 * Cached for 60 s. Drives tag picker in the document edit panel.
 */
export function useTags(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.tags(),
    queryFn: getTags,
    staleTime: 60_000,
  });
}

/**
 * Create a correspondent in Paperless-ngx — POST /api/correspondents.
 *
 * Invalidates the correspondents query on success so pickers re-fetch the
 * updated list (including the newly created entry).
 */
export function useCreateCorrespondent(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createCorrespondent(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.correspondents() });
    },
  });
}

/**
 * Create a document type in Paperless-ngx — POST /api/document-types.
 *
 * Invalidates the document-types query on success so pickers re-fetch the
 * updated list (including the newly created entry).
 */
export function useCreateDocumentType(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createDocumentType(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.documentTypes() });
    },
  });
}

/**
 * Create a tag in Paperless-ngx — POST /api/tags.
 *
 * Invalidates the tags query on success so pickers re-fetch the updated list
 * (including the newly created entry).
 */
export function useCreateTag(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createTag(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tags() });
    },
  });
}
