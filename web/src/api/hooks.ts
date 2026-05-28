/**
 * TanStack Query hooks — the ONLY way the rest of the app calls the backend.
 *
 * All server state lives here; no component or feature calls `fetch` directly
 * (CODE_GUIDELINES §12.6). The hooks are built on `client.ts` which owns the
 * base URL, `credentials: 'include'`, and error normalisation.
 *
 * Allowed deps: @tanstack/react-query, client.ts, types.ts
 * (leaf module — CODE_GUIDELINES §12.3, never imports components/features/pages).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import {
  search,
  getFacets,
  getStats,
  login,
  logout,
  me,
  setup,
  setupStatus,
  publicStats,
  getRecentSearches,
  getUsers,
  createUser,
  updateUser,
  deleteUser,
  getApiKeys,
  createApiKey,
  updateApiKey,
  deleteApiKey,
  getSettings,
  updateSettings,
  testConnection,
  getDocuments,
  getDocument,
  getIndexStatus,
  getIndexActivity,
  getFailedDocuments,
  rebuildIndex,
  postReconcile,
  patchDocument,
  reclassifyDocument,
  retranscribeDocument,
  deleteDocument,
  getCorrespondents,
  getDocumentTypes,
  getTags,
  createCorrespondent,
  createDocumentType,
  createTag,
} from './client';
import type {
  SearchRequest,
  SearchResponse,
  FacetsResponse,
  StatsResponse,
  LoginRequest,
  LoginResponse,
  MeResponse,
  SetupRequest,
  SetupResponse,
  SetupStatus,
  PublicStats,
  RecentSearchesResponse,
  CreateUserRequest,
  UpdateUserRequest,
  UsersResponse,
  UserResponse,
  CreateApiKeyRequest,
  UpdateApiKeyRequest,
  ApiKeysResponse,
  CreateApiKeyResponse,
  ApiKeyEnvelope,
  SettingsResponse,
  UpdateSettingsRequest,
  TestConnectionRequest,
  TestConnectionResponse,
  DocumentsQuery,
  DocumentsResponse,
  LibraryDocument,
  IndexStatusResponse,
  IndexActivityResponse,
  IndexFailedResponse,
  RebuildResponse,
  TaxonomyItem,
  DocumentPatch,
} from './types';

// ---------------------------------------------------------------------------
// Query key factory — keeps cache keys consistent and avoids magic strings
// ---------------------------------------------------------------------------

const queryKeys = {
  search: (req: SearchRequest) => ['search', req] as const,
  facets: () => ['facets'] as const,
  stats: () => ['stats'] as const,
  me: () => ['auth', 'me'] as const,
  setupStatus: () => ['setup', 'status'] as const,
  publicStats: () => ['stats', 'public'] as const,
  recentSearches: () => ['recent-searches'] as const,
  users: () => ['users'] as const,
  apiKeys: () => ['api-keys'] as const,
  settings: () => ['settings'] as const,
  documents: (query: DocumentsQuery) => ['documents', query] as const,
  document: (id: number) => ['document', id] as const,
  indexStatus: () => ['index', 'status'] as const,
  indexActivity: () => ['index', 'activity'] as const,
  failedDocuments: () => ['index', 'failed'] as const,
  correspondents: () => ['correspondents'] as const,
  documentTypes: () => ['document-types'] as const,
  tags: () => ['tags'] as const,
} as const;

/** The `me` query key — exported so `useAuth` and `ProtectedRoute` agree on it. */
export const ME_QUERY_KEY = ['auth', 'me'] as const;

// ---------------------------------------------------------------------------
// Query hooks
// ---------------------------------------------------------------------------

/**
 * Execute a semantic search query.
 *
 * Disabled when `query` is empty so the hook stays in `pending` state without
 * issuing a request — avoids a pointless round-trip on initial render.
 */
export function useSearch(
  req: SearchRequest,
): UseQueryResult<SearchResponse, Error> {
  return useQuery({
    queryKey: queryKeys.search(req),
    queryFn: () => search(req),
    enabled: req.query.trim().length > 0,
  });
}

/** Fetch taxonomy facets for the filter panel. */
export function useFacets(): UseQueryResult<FacetsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.facets(),
    queryFn: getFacets,
  });
}

/** Fetch index statistics. */
export function useStats(): UseQueryResult<StatsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.stats(),
    queryFn: getStats,
  });
}

/**
 * Fetch a page of the library document list.
 *
 * `placeholderData` keeps the previous page on screen while the next page
 * loads — paging through the library does not flash an empty grid. The query
 * key includes the full `DocumentsQuery`, so changing any filter, the sort,
 * or the page produces a distinct cache entry.
 */
export function useDocuments(
  query: DocumentsQuery,
): UseQueryResult<DocumentsResponse, Error> {
  return useQuery({
    queryKey: queryKeys.documents(query),
    queryFn: () => getDocuments(query),
    placeholderData: (previous) => previous,
  });
}

/**
 * The signed-in user's recent-search history — GET /api/recent-searches.
 *
 * Drives the idle search screen's "Recent searches" strip. `retry: false` so
 * a 401 (session gone) resolves to an error state at once rather than
 * retrying; the idle screen treats any error as "no recent searches" and
 * simply omits the strip.
 */
export function useRecentSearches(): UseQueryResult<RecentSearchesResponse, Error> {
  return useQuery({
    queryKey: queryKeys.recentSearches(),
    queryFn: getRecentSearches,
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// Auth query hooks
// ---------------------------------------------------------------------------

/**
 * The current authenticated user — GET /api/auth/me.
 *
 * `useAuth` is built on this hook. `retry: false` so a 401 (not signed in)
 * resolves to an error state immediately rather than retrying.
 *
 * `staleTime: 0` — deliberately short (differs from the 60 s global default)
 * so a login or logout flips the auth state on the very next mount.
 *
 * `enabled` — pass `false` when setup is still needed to avoid a guaranteed-
 * useless 401 round-trip on every first-run page load.
 */
export function useMe({ enabled = true }: { enabled?: boolean } = {}): UseQueryResult<MeResponse, Error> {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: me,
    retry: false,
    staleTime: 0,
    enabled,
  });
}

/**
 * Whether first-run setup is still needed — GET /api/setup/status.
 *
 * Public; used by the bootstrap gate before the user is known. `retry: false`
 * so a transient failure does not stall the gate.
 *
 * `staleTime: 0` — intentionally short (same reasoning as `useMe`): the gate
 * must reflect a just-completed setup without a stale cache masking it.
 */
export function useSetupStatus(): UseQueryResult<SetupStatus, Error> {
  return useQuery({
    queryKey: queryKeys.setupStatus(),
    queryFn: setupStatus,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Minimal public splash counts — GET /api/stats/public.
 *
 * Used only by the login splash. `retry: false` and a callers-must-degrade
 * contract: the login screen omits the numbers when this errors.
 *
 * `staleTime: 60_000` — document counts change infrequently; one minute's
 * staleness is fine for an informational splash display. This differs from
 * the `staleTime: 0` on `useMe` / `useSetupStatus`, which are auth-critical.
 */
export function usePublicStats(): UseQueryResult<PublicStats, Error> {
  return useQuery({
    queryKey: queryKeys.publicStats(),
    queryFn: publicStats,
    retry: false,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks
// ---------------------------------------------------------------------------

/**
 * Login mutation — POST /api/auth/login.
 *
 * On success the server sets an `HttpOnly` session cookie and the `me` query
 * is invalidated so `useAuth` re-resolves to the signed-in user. On failure
 * the mutation exposes `Unauthenticated` (401) or `ApiError` (403 suspended).
 */
export function useLogin(): UseMutationResult<LoginResponse, Error, LoginRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: login,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

/**
 * Logout mutation — POST /api/auth/logout.
 *
 * On success the `me` query cache is cleared so `useAuth` immediately reports
 * the user as signed out and the router sends them to `/login`.
 */
export function useLogout(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => {
      queryClient.setQueryData(queryKeys.me(), undefined);
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

/**
 * First-run setup mutation — POST /api/setup.
 *
 * Creates the first admin account. On success the `setup-status` and `me`
 * queries are invalidated so the bootstrap gate re-resolves — the freshly
 * created admin is signed in by the same response's session cookie.
 * On failure: `ApiError` with status 403 (bad token) or 409 (already set up).
 */
export function useSetup(): UseMutationResult<SetupResponse, Error, SetupRequest> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: setup,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.setupStatus() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.me() });
    },
  });
}

// ---------------------------------------------------------------------------
// User-management hooks (Wave 3 — Access Control)
//
// The mutations invalidate the `users` query so the Users table re-fetches
// after every create / edit / delete.
// ---------------------------------------------------------------------------

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

/**
 * Update-user mutation — PATCH /api/users/{id}.
 *
 * Takes `{ id, body }` so a single hook covers role changes, suspension and
 * password resets. Invalidates the users list on success.
 */
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

// ---------------------------------------------------------------------------
// API-key hooks (Wave 3 — Access Control)
//
// The mutations invalidate the `apiKeys` query so the keys table re-fetches
// after a key is minted or revoked.
// ---------------------------------------------------------------------------

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
 * The success payload carries the full one-time `secret`. The caller shows
 * it once and discards it. Invalidates the keys list so the new key appears.
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

/**
 * Edit-API-key mutation — PATCH /api/api-keys/{id}.
 *
 * Editing is owner-only on the server. Invalidates the keys list so the
 * edited key's new name / scopes / expiry show in the table.
 */
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

// ---------------------------------------------------------------------------
// Settings hooks (Wave 4 — Settings)
//
// `useUpdateSettings` invalidates the settings query so the screen re-reads
// the persisted state after a save — the PUT response is also the new state,
// but invalidation keeps any other settings reader consistent.
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Index-operations hooks (Wave 6 — Index)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Shareable-URL hooks (Wave 7 — Shareable URLs)
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Document editing + taxonomy hooks (Wave 8/9 — Document page)
// ---------------------------------------------------------------------------

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
 * Partially update a document's metadata — PATCH /api/documents/{id}.
 *
 * On success:
 * - Writes the updated document directly into the `['document', id]` cache
 *   entry to avoid a redundant GET round-trip.
 * - Invalidates `['documents']` so the library list re-fetches with the
 *   new title / correspondent / type.
 * - Invalidates `['search']` so any cached search results that include the
 *   document are refreshed.
 */
export function useUpdateDocument(): UseMutationResult<
  LibraryDocument,
  Error,
  { id: number; patch: DocumentPatch }
> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, patch }) => patchDocument(id, patch),
    onSuccess: (updated, vars) => {
      qc.setQueryData(queryKeys.document(vars.id), updated);
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
