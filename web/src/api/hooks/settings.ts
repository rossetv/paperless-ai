/**
 * Settings query and mutation hooks — Wave 4.
 *
 * `useUpdateSettings` invalidates the settings query so the screen re-reads
 * the persisted state after a save — the PUT response is also the new state,
 * but invalidation keeps any other settings reader consistent.
 *
 * Allowed deps: @tanstack/react-query, client, types, hooks/keys
 * (leaf module — CODE_GUIDELINES §12.3).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { getSettings, updateSettings, testConnection } from '../client';
import type {
  SettingsResponse,
  UpdateSettingsRequest,
  TestConnectionRequest,
  TestConnectionResponse,
} from '../types';
import { queryKeys } from './keys';

/** Fetch the current configuration — GET /api/settings. */
export function useSettings(): UseQueryResult<SettingsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.settings(),
    queryFn: getSettings,
  });
}

/** Save changed configuration — PUT /api/settings. Invalidates the settings query. */
export function useUpdateSettings(): UseMutationResult<
  SettingsResponse,
  Error,
  UpdateSettingsRequest
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings() });
    },
  });
}

/**
 * Probe the Paperless connection — POST /api/settings/test-connection.
 *
 * A one-shot mutation: it touches no query cache. The caller reads
 * `isPending` / `data` / `error` to drive the inline test-result UI.
 */
export function useTestConnection(): UseMutationResult<
  TestConnectionResponse,
  Error,
  TestConnectionRequest
> {
  return useMutation({
    mutationFn: testConnection,
  });
}
