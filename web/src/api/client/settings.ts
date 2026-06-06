/**
 * Settings endpoint functions — Wave 4.
 *
 * Admin-only on the server. A non-admin caller gets a 403, surfaced as
 * `ApiError`; the route guard prevents a non-admin reaching the screen at all.
 *
 * Allowed deps: core, types (leaf module — CODE_GUIDELINES §12.3).
 */

import type {
  SettingsResponse,
  UpdateSettingsRequest,
  TestConnectionRequest,
  TestConnectionResponse,
} from '../types';
import { BASE_URL, request } from './core';

/** GET /api/settings — the current configuration values plus their metadata. */
export async function getSettings(): Promise<SettingsResponse> {
  return request<SettingsResponse>(`${BASE_URL}/api/settings`, { method: 'GET' });
}

/**
 * PUT /api/settings — persist changed configuration values.
 *
 * The body carries ONLY the keys the user changed. The server validates the
 * whole resulting config; a validation failure surfaces as `ApiError` (400).
 * The response is the re-read state — the source of truth after the save.
 */
export async function updateSettings(
  body: UpdateSettingsRequest,
): Promise<SettingsResponse> {
  return request<SettingsResponse>(`${BASE_URL}/api/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/settings/test-connection — probe the Paperless connection.
 *
 * Takes the LIVE form values (not the saved config) so the user can test a
 * URL/token pair before committing it. A reachable-but-rejected probe
 * resolves to `{ ok: false, detail }`; a network failure throws `ApiError`.
 */
export async function testConnection(
  body: TestConnectionRequest,
): Promise<TestConnectionResponse> {
  return request<TestConnectionResponse>(
    `${BASE_URL}/api/settings/test-connection`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
}
