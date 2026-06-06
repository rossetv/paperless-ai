/**
 * Wire types — re-export barrel.
 *
 * The 658-line monolith has been split into domain modules under api/types/:
 *   auth.ts     — User, SetupStatus/Request/Response, Login*, MeResponse, PublicStats
 *   access.ts   — users CRUD + API-key types (Wave 3)
 *   search.ts   — search request/response, facets, recent-searches (Wave 2)
 *   settings.ts — SettingItem, SettingsResponse, TestConnection* (Wave 4)
 *   library.ts  — DocumentsQuery, LibraryDocument, TaxonomyItem, DocumentPatch (Wave 5/8)
 *   index.ts    — DaemonStatus, IndexStatus*, ReconcileCycle, FailedDocument, RebuildResponse (Wave 6)
 *
 * All existing imports (`from './api/types'`) continue to resolve here.
 * New code is encouraged to import directly from the domain module it needs.
 *
 * Allowed deps: domain modules above only (CODE_GUIDELINES §12.3).
 */

export type * from './types/auth';
export type * from './types/access';
export type * from './types/search';
export type * from './types/settings';
export type * from './types/library';
export type * from './types/index';
