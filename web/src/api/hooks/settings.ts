/** Settings query and mutation hooks. */

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

/**
 * Save changed configuration — PUT /api/settings.
 *
 * Invalidates the settings query even though the response is the new state, so
 * every other settings reader stays consistent.
 */
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

/** Probe the Paperless connection — POST /api/settings/test-connection. Touches no cache. */
export function useTestConnection(): UseMutationResult<
  TestConnectionResponse,
  Error,
  TestConnectionRequest
> {
  return useMutation({
    mutationFn: testConnection,
  });
}
