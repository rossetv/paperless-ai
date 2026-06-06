/**
 * Auth and account wire types — mirrors the Wave 1 backend contract.
 *
 * Covers setup, login, and the current-user query. These are the leaf types
 * the rest of the access-control and auth domains build on.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

/** A user account, as returned by the server. Mirrors the Wave 1 contract. */
export interface User {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  role: 'admin' | 'member' | 'readonly';
  status: 'active' | 'suspended';
  created_at: string;
  last_login_at: string | null;
}

/** Response body for GET /api/setup/status. */
export interface SetupStatus {
  /** True when no users exist yet — the first-run setup screen must show. */
  needed: boolean;
}

/** Body for POST /api/setup — create the first admin account. */
export interface SetupRequest {
  /** The setup token printed to the container logs. */
  token: string;
  /** Desired admin username. */
  username: string;
  /** Desired admin password. */
  password: string;
}

/** Response body for POST /api/setup — the freshly created admin. */
export interface SetupResponse {
  user: User;
}

/** Body for POST /api/auth/login. */
export interface LoginRequest {
  username: string;
  password: string;
  /** "Keep me signed in for 7 days" — extends the session TTL. */
  remember: boolean;
}

/** Response body for POST /api/auth/login. */
export interface LoginResponse {
  user: User;
}

/** Response body for GET /api/auth/me — the current user. */
export interface MeResponse {
  user: User;
}

/** Response body for GET /api/stats/public — splash counts only. */
export interface PublicStats {
  document_count: number;
  chunk_count: number;
}
