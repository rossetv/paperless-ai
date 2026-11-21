/**
 * User-management and API-key hooks. Every mutation invalidates its list query
 * so the table re-fetches.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  getApiKeys,
  createApiKey,
  updateApiKey,
  deleteApiKey,
} from '../client';
import type {
  CreateUserRequest,
  UpdateUserRequest,
  UsersResponse,
  UserResponse,
  CreateApiKeyRequest,
  UpdateApiKeyRequest,
  ApiKeysResponse,
  CreateApiKeyResponse,
  ApiKeyEnvelope,
} from '../types';
import { queryKeys } from './keys';

/** Fetch every user account — GET /api/users. */
export function useUsers(): UseQueryResult<UsersResponse, Error> {
  return useQuery({
    queryKey: queryKeys.users(),
    queryFn: getUsers,
  });
}

/** Create-user mutation — POST /api/users. Invalidates the users list. */
export function useCreateUser(): UseMutationResult<
  UserResponse,
  Error,
  CreateUserRequest
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}

/** Update-user mutation — PATCH /api/users/{id}; covers role, suspension and password reset. */
export function useUpdateUser(): UseMutationResult<
  UserResponse,
  Error,
  { id: number; body: UpdateUserRequest }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }) => updateUser(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}

/** Delete-user mutation — DELETE /api/users/{id}. Invalidates the users list. */
export function useDeleteUser(): UseMutationResult<void, Error, number> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users() });
    },
  });
}

/** Fetch the API keys visible to the caller — GET /api/api-keys. */
export function useApiKeys(): UseQueryResult<ApiKeysResponse, Error> {
  return useQuery({
    queryKey: queryKeys.apiKeys(),
    queryFn: getApiKeys,
  });
}

/**
 * Create-API-key mutation — POST /api/api-keys.
 *
 * The payload carries the one-time `secret`; the caller shows it once and discards it.
 */
export function useCreateApiKey(): UseMutationResult<
  CreateApiKeyResponse,
  Error,
  CreateApiKeyRequest
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createApiKey,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys() });
    },
  });
}

/** Edit-API-key mutation — PATCH /api/api-keys/{id} (owner-only on the server). */
export function useUpdateApiKey(): UseMutationResult<
  ApiKeyEnvelope,
  Error,
  { id: number; body: UpdateApiKeyRequest }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }) => updateApiKey(id, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys() });
    },
  });
}

/** Delete / revoke API-key mutation — DELETE /api/api-keys/{id}. */
export function useDeleteApiKey(): UseMutationResult<void, Error, number> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteApiKey,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys() });
    },
  });
}
