/**
 * Typed fetch wrapper — the single point of backend contact for the React SPA.
 *
 * Re-export barrel — the 692-line monolith has been split into domain modules
 * under api/client/:
 *   core.ts      — BASE_URL, Unauthenticated, ApiError, request helper
 *   auth.ts      — setup, login, logout, me, publicStats
 *   search.ts    — search, getFacets, getStats, getHealthz, postReconcile,
 *                  getRecentSearches, documentPdfUrl, documentThumbUrl
 *   access.ts    — users CRUD + API-key endpoints
 *   settings.ts  — getSettings, updateSettings, testConnection
 *   library.ts   — getDocuments, getDocument, patchDocument,
 *                  reclassifyDocument, retranscribeDocument, deleteDocument
 *   index.ts     — getIndexStatus, getIndexActivity, getFailedDocuments,
 *                  rebuildIndex
 *   taxonomy.ts  — getCorrespondents, getDocumentTypes, getTags,
 *                  createCorrespondent, createDocumentType, createTag
 *
 * All existing imports (`from './api/client'`) continue to resolve here.
 * New code is encouraged to import directly from the domain module it needs.
 *
 * Security invariant (spec §7.3, §9.2):
 *   - Every request sends `credentials: 'include'` so the signed `HttpOnly`
 *     session cookie is attached automatically by the browser.
 *   - No credential is ever stored in or shipped with the frontend bundle.
 *     Authentication is done via the login handshake → cookie; the JS bundle
 *     never sees or forwards any raw secret.
 *
 * Allowed deps: domain modules above only (CODE_GUIDELINES §12.3).
 */

export * from './client/core';
export * from './client/auth';
export * from './client/search';
export * from './client/searchStream';
export * from './client/access';
export * from './client/settings';
export * from './client/library';
export * from './client/index';
export * from './client/taxonomy';
