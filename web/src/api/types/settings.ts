/**
 * Settings / configuration wire types — Wave 4.
 *
 * Covers the GET/PUT /api/settings endpoints and the test-connection probe.
 * The 51 config keys are field names of the server's `Settings` dataclass;
 * `SettingItem.key` carries those names.
 *
 * Allowed deps: none (leaf module — CODE_GUIDELINES §12.3).
 */

/**
 * One configuration key as the server returns it.
 *
 * `value` is the effective value as a STRING, or `null` when the key is on
 * its coded default. For a secret key it is a fixed mask string, never the
 * real secret. The field model in `features/settings` parses `value` to the
 * key's real type (number / boolean / CSV list).
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
  /**
   * The coded default for this key as a string, or null for secrets and
   * optional keys that have no meaningful coded default. Used by the Settings
   * screen to display the default value when `source` is `'default'` and
   * `value` is null.
   */
  default_value: string | null;
}

/**
 * Response body for GET /api/settings and PUT /api/settings.
 *
 * A flat list, one item per config key. PUT returns this same shape — the
 * re-read state — so the screen refreshes itself from the one response.
 */
export interface SettingsResponse {
  settings: SettingItem[];
  /**
   * Set by PUT when the save changed a re-index key (embedding model or
   * chunking) and therefore forced a full index rebuild — re-embedding every
   * document. Always false on GET. The Settings screen surfaces it as a toast.
   */
  reindex_triggered: boolean;
}

/**
 * Body for PUT /api/settings.
 *
 * `changes` carries only the keys the user changed, each as a STRING — the
 * config table is string-only, so the frontend serialises numbers, booleans
 * and CSV lists to strings before posting. An unchanged masked secret is
 * omitted — the server keeps the stored value when a key is absent.
 */
export interface UpdateSettingsRequest {
  changes: Record<string, string>;
}

/** Body for POST /api/settings/test-connection — the current form values. */
export interface TestConnectionRequest {
  /** The Paperless server URL to probe — the live form value, not the saved one. */
  paperless_url: string;
  /**
   * The Paperless API token to probe with — the live form value. An empty
   * string means "probe with the stored token" (the masked-token path: the
   * user has not replaced the secret).
   */
  paperless_token: string;
  /**
   * The service to probe. When present, the backend routes the request to the
   * appropriate connector. Omitting it defaults to the Paperless probe for
   * backwards compatibility.
   */
  service?: 'paperless' | 'openai' | 'ollama';
  /**
   * The live OpenAI API key to probe with. Only sent when `service === 'openai'`
   * and the key is not masked (user has replaced it in the draft).
   */
  openai_api_key?: string;
  /**
   * The live Ollama base URL to probe with. Only sent when `service === 'ollama'`
   * and the URL is not masked.
   */
  ollama_base_url?: string;
}

/**
 * Response body for POST /api/settings/test-connection.
 *
 * `ok` is true when the round-trip succeeded; `document_count` is then the
 * count Paperless reported. `ok` is false (with `document_count: 0` and an
 * explanatory `detail`) when the server was reached but the token or URL was
 * rejected, or the host was unreachable.
 */
export interface TestConnectionResponse {
  ok: boolean;
  document_count: number;
  detail: string;
}
