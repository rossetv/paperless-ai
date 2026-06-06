/**
 * TanStack Query key factory — keeps cache keys consistent across all hook
 * modules and avoids magic strings.
 *
 * This module is the single source of truth for every query key used by the
 * hooks layer. All sibling hook modules import from here; no other file
 * should hard-code a query key array.
 *
 * Allowed deps: types (leaf module — CODE_GUIDELINES §12.3).
 */

import type { SearchRequest, DocumentsQuery } from '../types';

// ---------------------------------------------------------------------------
// Internal factory — not exported; sibling modules import the typed object
// ---------------------------------------------------------------------------

export const queryKeys = {
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
