/** Settings and test-connection wire types. */

/**
 * One configuration key as the server returns it. For a secret key `value` is
 * the fixed mask, never the real secret; `features/settings` parses it to the real type.
 */
export interface SettingItem {
  /** The canonical config-key name (a `Settings`-dataclass field name). */
  key: string;
  /** The effective value as a string, or null when on the coded default. */
  value: string | null;
  /** Where the value came from: 'database' | 'environment' | 'default'. */
  source: string;
  /** True for secret keys — `value` is masked; the UI offers a reveal. */
  is_secret: boolean;
  /** True when changing this key requires a full document re-index. */
  requires_reindex: boolean;
  /** The coded default as a string; null for secrets and keys without a meaningful one. */
  default_value: string | null;
}

/** Response body for GET and PUT /api/settings; PUT returns the re-read state. */
export interface SettingsResponse {
  settings: SettingItem[];
  /** True when a PUT changed a re-index key and forced a full rebuild; always false on GET. */
  reindex_triggered: boolean;
}

/**
 * Body for PUT /api/settings: only the changed keys, each serialised to a string
 * because the config table is string-only. An unchanged masked secret is omitted.
 */
export interface UpdateSettingsRequest {
  changes: Record<string, string>;
}

/**
 * The mask the backend puts in place of a stored secret (`_SECRET_MASK` in
 * `src/search/settings_routes.py`). Compare with exact equality, never containment.
 */
export const SECRET_MASK = '********';

/** Body for POST /api/settings/test-connection — the current form values. */
export interface TestConnectionRequest {
  /** The Paperless server URL to probe — the live form value, not the saved one. */
  paperless_url: string;
  /** The live form token; an empty string means "probe with the stored token". */
  paperless_token: string;
  /** The service to probe; omitted means Paperless. */
  service?: 'paperless' | 'openai' | 'ollama';
  /** Sent only for `service === 'openai'` when the user has replaced the masked key. */
  openai_api_key?: string;
  /** Sent only for `service === 'ollama'` when the URL is not masked. */
  ollama_base_url?: string;
}

/**
 * Response body for POST /api/settings/test-connection. On failure (rejected or
 * unreachable) `ok` is false, `document_count` is 0 and `detail` explains.
 */
export interface TestConnectionResponse {
  ok: boolean;
  document_count: number;
  detail: string;
}
