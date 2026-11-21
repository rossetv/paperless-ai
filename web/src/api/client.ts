/**
 * The typed fetch API for the SPA, re-exported from the domain modules in `client/`.
 *
 * Every request sends `credentials: 'include'` so the browser attaches the
 * `HttpOnly` session cookie; no credential is stored in or shipped with the bundle.
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
