/**
 * Correspondent, document-type and tag hooks. Lists are cached for 60 s; each
 * create invalidates its list so pickers re-fetch.
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

/** All correspondents in Paperless-ngx — GET /api/correspondents. */
export function useCorrespondents(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.correspondents(),
    queryFn: getCorrespondents,
    staleTime: 60_000,
  });
}

/** All document types in Paperless-ngx — GET /api/document-types. */
export function useDocumentTypes(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.documentTypes(),
    queryFn: getDocumentTypes,
    staleTime: 60_000,
  });
}

/** All tags in Paperless-ngx — GET /api/tags. */
export function useTags(): UseQueryResult<TaxonomyItem[], Error> {
  return useQuery({
    queryKey: queryKeys.tags(),
    queryFn: getTags,
    staleTime: 60_000,
  });
}

/** Create a correspondent in Paperless-ngx — POST /api/correspondents. */
export function useCreateCorrespondent(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createCorrespondent(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.correspondents() });
    },
  });
}

/** Create a document type in Paperless-ngx — POST /api/document-types. */
export function useCreateDocumentType(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createDocumentType(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.documentTypes() });
    },
  });
}

/** Create a tag in Paperless-ngx — POST /api/tags. */
export function useCreateTag(): UseMutationResult<TaxonomyItem, Error, string> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name) => createTag(name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.tags() });
    },
  });
}
