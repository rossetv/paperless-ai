/**
 * TanStack Query hooks — re-export barrel.
 *
 * The 787-line monolith has been split into domain modules under api/hooks/:
 *   keys.ts       — queryKeys factory + ME_QUERY_KEY (shared by all hook modules)
 *   search.ts     — useSearch, useFacets, useStats, useDocuments, useRecentSearches
 *   auth.ts       — useMe, useSetupStatus, usePublicStats, useLogin, useLogout, useSetup
 *   access.ts     — useUsers, useCreateUser, useUpdateUser, useDeleteUser,
 *                   useApiKeys, useCreateApiKey, useUpdateApiKey, useDeleteApiKey
 *   settings.ts   — useSettings, useUpdateSettings, useTestConnection
 *   index-ops.ts  — useIndexStatus, useIndexActivity, useFailedDocuments,
 *                   useRebuildIndex, useReconcile
 *   library.ts    — useDocument, useUpdateDocument, useReclassifyDocument,
 *                   useRetranscribeDocument, useDeleteDocument
 *   taxonomy.ts   — useCorrespondents, useDocumentTypes, useTags,
 *                   useCreateCorrespondent, useCreateDocumentType, useCreateTag
 *
 * All existing imports (`from './api/hooks'`) continue to resolve here.
 * New code is encouraged to import directly from the domain module it needs.
 *
 * Allowed deps: domain modules above only (CODE_GUIDELINES §12.3).
 */

export * from './hooks/keys';
export * from './hooks/search';
export * from './hooks/auth';
export * from './hooks/access';
export * from './hooks/settings';
export * from './hooks/index-ops';
export * from './hooks/library';
export * from './hooks/taxonomy';
