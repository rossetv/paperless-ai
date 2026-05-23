/**
 * The declarative model behind the Settings screen.
 *
 * Rather than hand-author nine cards of form rows, the Settings screen
 * renders from this data: an ordered list of section descriptors, each
 * holding an ordered list of field descriptors. A field descriptor binds one
 * config key (a `Settings`-dataclass field name) to a control kind, a label,
 * a hint and any control-specific options.
 *
 * Adding or retiring a config key is a change to this file alone — the screen
 * components are generic.
 *
 * Tier: features/ — this encodes domain knowledge of the config keys.
 */

/** A − / + numeric control. `min`/`max` clamp; `suffix` is an optional unit. */
export interface NumberControl {
  kind: 'number';
  min: number;
  max?: number;
  suffix?: string;
}

/** A single-line text control. `mono` renders a monospace face. */
export interface TextControl {
  kind: 'text';
  mono?: boolean;
  placeholder?: string;
}

/** A masked secret control — a SecretField with a reveal toggle. */
export interface SecretControl {
  kind: 'secret';
}

/** An on/off Toggle. */
export interface ToggleControl {
  kind: 'toggle';
}

/** A Segmented single-choice control over a fixed option set. */
export interface SegmentedControl {
  kind: 'segmented';
  options: { value: string; label: string }[];
}

/** A dropdown over a fixed option set. */
export interface SelectControl {
  kind: 'select';
  options: { value: string; label: string }[];
}

/**
 * A comma-separated list control — an editable text field whose value is a
 * `string[]`. Used for AI_MODELS and OCR_REFUSAL_MARKERS.
 */
export interface ListControl {
  kind: 'list';
}

/** The discriminated union of every control kind. */
export type FieldControl =
  | NumberControl
  | TextControl
  | SecretControl
  | ToggleControl
  | SegmentedControl
  | SelectControl
  | ListControl;

/** One editable configuration field. */
export interface SettingsField {
  /** The config-key name — a `Settings`-dataclass field name. */
  key: string;
  /** The visible row label. */
  label: string;
  /** One-line explanatory hint. */
  hint: string;
  /** The control to render for this field. */
  control: FieldControl;
  /**
   * True for secret keys (PAPERLESS_TOKEN, OPENAI_API_KEY). The screen masks
   * the value and only sends the key back when the user changes it. A field
   * with `control.kind === 'secret'` is always also `secret: true`.
   */
  secret?: boolean;
}

/** One section of the Settings screen — one SectionCard's worth of fields. */
export interface SettingsSection {
  /** Stable anchor id — matches the SettingsSideNav Configuration item id. */
  id: string;
  /** The section title. */
  title: string;
  /** The section subtitle, shown under the title. */
  subtitle: string;
  /** The fields, top to bottom. */
  fields: SettingsField[];
}

/** A small fixed model-identifier list, reused by the planner/answer selects. */
const MODEL_OPTIONS = [
  { value: 'gpt-5.4-mini', label: 'gpt-5.4-mini' },
  { value: 'gpt-5.4', label: 'gpt-5.4' },
  { value: 'o4-mini', label: 'o4-mini' },
];

const EMBEDDING_MODEL_OPTIONS = [
  { value: 'text-embedding-3-small', label: 'text-embedding-3-small' },
  { value: 'text-embedding-3-large', label: 'text-embedding-3-large' },
];

/**
 * The nine settings sections, in display order.
 *
 * The order and the section ids match the SettingsSideNav Configuration
 * group. Field order within a section follows the handoff `settings.jsx`.
 */
export const SETTINGS_SECTIONS: SettingsSection[] = [
  {
    id: 'paperless',
    title: 'Paperless Connection',
    subtitle: 'The Paperless-ngx instance your daemons read from and write to.',
    fields: [
      {
        key: 'PAPERLESS_URL',
        label: 'Server URL',
        hint: 'API base URL of your Paperless-ngx instance, reachable from this container.',
        control: { kind: 'text', mono: true },
      },
      {
        key: 'PAPERLESS_PUBLIC_URL',
        label: 'Public URL',
        hint: 'Browser-facing base URL for document deep-links. Falls back to the server URL.',
        control: { kind: 'text', mono: true },
      },
      {
        key: 'PAPERLESS_TOKEN',
        label: 'API token',
        hint: 'Found in Paperless under Settings → Users & Groups → API Token.',
        control: { kind: 'secret' },
        secret: true,
      },
    ],
  },
  {
    id: 'llm',
    title: 'LLM Provider',
    subtitle: 'The model used for OCR, classification, planning and synthesis.',
    fields: [
      {
        key: 'LLM_PROVIDER',
        label: 'Provider',
        hint: 'OpenAI uses hosted models; Ollama uses a local instance. Embeddings always use OpenAI.',
        control: {
          kind: 'segmented',
          options: [
            { value: 'openai', label: 'OpenAI' },
            { value: 'ollama', label: 'Ollama' },
          ],
        },
      },
      {
        key: 'OPENAI_API_KEY',
        label: 'OpenAI API key',
        hint: 'Required for every process — embeddings always go through OpenAI.',
        control: { kind: 'secret' },
        secret: true,
      },
      {
        key: 'OLLAMA_BASE_URL',
        label: 'Ollama base URL',
        hint: 'Must end with /v1/. Ignored when the provider is OpenAI.',
        control: { kind: 'text', mono: true, placeholder: 'http://ollama.lan:11434/v1/' },
      },
      {
        key: 'AI_MODELS',
        label: 'Model fallback chain',
        hint: 'Tried in order; first success wins. Comma-separated model identifiers.',
        control: { kind: 'list' },
      },
    ],
  },
  {
    id: 'search',
    title: 'Search Server',
    subtitle: 'Tune the agentic search pipeline — planning, retrieval, synthesis.',
    fields: [
      {
        key: 'SEARCH_TOP_K',
        label: 'Top K',
        hint: 'How many documents are fed to the synthesiser.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'SEARCH_MAX_REFINEMENTS',
        label: 'Max refinements',
        hint: 'Agentic refinement steps. A hard ceiling of 3 is always enforced.',
        control: { kind: 'number', min: 0, max: 3 },
      },
      {
        key: 'SEARCH_PLANNER_MODEL',
        label: 'Planner model',
        hint: 'Cheaper model for structured query extraction.',
        control: { kind: 'select', options: MODEL_OPTIONS },
      },
      {
        key: 'SEARCH_ANSWER_MODEL',
        label: 'Answer model',
        hint: 'Stronger model for user-facing synthesis.',
        control: { kind: 'select', options: MODEL_OPTIONS },
      },
      {
        key: 'SEARCH_MAX_CONCURRENT',
        label: 'Max concurrent requests',
        hint: 'Bounds in-flight /api/search work via a global semaphore. 0 is unbounded.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'SEARCH_SESSION_TTL',
        label: 'Session TTL',
        hint: 'How long a signed session cookie stays valid after login.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
      {
        key: 'SEARCH_SERVER_HOST',
        label: 'Server host',
        hint: 'The interface the search server binds. 0.0.0.0 binds all interfaces.',
        control: { kind: 'text', mono: true },
      },
      {
        key: 'SEARCH_SERVER_PORT',
        label: 'Server port',
        hint: 'The TCP port the search server listens on.',
        control: { kind: 'number', min: 1, max: 65535 },
      },
    ],
  },
  {
    id: 'embed',
    title: 'Embeddings & Index',
    subtitle: 'How the indexer chunks, embeds and reconciles your library.',
    fields: [
      {
        key: 'EMBEDDING_MODEL',
        label: 'Embedding model',
        hint: 'Always OpenAI. Changing this triggers a full rebuild on the next reconcile.',
        control: { kind: 'select', options: EMBEDDING_MODEL_OPTIONS },
      },
      {
        key: 'EMBEDDING_DIMENSIONS',
        label: 'Embedding dimensions',
        hint: 'Must match the model. The schema is locked to this on the first reconcile.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'EMBEDDING_MAX_CONCURRENT',
        label: 'Embedding max concurrent',
        hint: 'Global cap on concurrent embedding calls. 0 is unbounded.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CHUNK_SIZE',
        label: 'Chunk size',
        hint: 'Characters per text chunk fed to embedding.',
        control: { kind: 'number', min: 1, suffix: 'chars' },
      },
      {
        key: 'CHUNK_OVERLAP',
        label: 'Chunk overlap',
        hint: 'Adjacent-chunk overlap, so boundaries do not split context. Must be < chunk size.',
        control: { kind: 'number', min: 0, suffix: 'chars' },
      },
      {
        key: 'RECONCILE_INTERVAL',
        label: 'Reconcile interval',
        hint: 'Seconds between incremental sync cycles.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
      {
        key: 'DELETION_SWEEP_INTERVAL',
        label: 'Deletion sweep interval',
        hint: 'Seconds between full deletion sweeps.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
    ],
  },
  {
    id: 'ocr',
    title: 'OCR',
    subtitle: 'Vision-model transcription of scanned pages.',
    fields: [
      {
        key: 'OCR_DPI',
        label: 'OCR DPI',
        hint: 'Higher DPI gives better accuracy and larger images. 300 is a good default.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'OCR_MAX_SIDE',
        label: 'Max image side',
        hint: 'Pages are thumbnailed to fit this longest-edge size before submission.',
        control: { kind: 'number', min: 1, suffix: 'px' },
      },
      {
        key: 'OCR_INCLUDE_PAGE_MODELS',
        label: 'Include model in page headers',
        hint: 'Tag each OCR-d page with the model that transcribed it.',
        control: { kind: 'toggle' },
      },
      {
        key: 'OCR_REFUSAL_MARKERS',
        label: 'Refusal markers',
        hint: 'Comma-separated phrases (case-insensitive). If detected, the next model is tried.',
        control: { kind: 'list' },
      },
    ],
  },
  {
    id: 'classify',
    title: 'Classification',
    subtitle: 'Metadata enrichment — title, correspondent, type, tags.',
    fields: [
      {
        key: 'CLASSIFY_MAX_PAGES',
        label: 'Max pages sent to classifier',
        hint: 'Keeps the first N pages of OCR text. 0 means no limit.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_TAIL_PAGES',
        label: 'Tail pages',
        hint: 'Extra pages from the end of the document, included when truncating.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_TAG_LIMIT',
        label: 'Tag limit',
        hint: 'Max optional tags to keep. Required tags (year, country) do not count.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_TAXONOMY_LIMIT',
        label: 'Taxonomy context limit',
        hint: 'Max correspondents / types / tags included in the LLM prompt as context.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_MAX_CHARS',
        label: 'Max characters',
        hint: 'Hard character cap on the classifier prompt. 0 means no cap.',
        control: { kind: 'number', min: 0, suffix: 'chars' },
      },
      {
        key: 'CLASSIFY_MAX_TOKENS',
        label: 'Max tokens',
        hint: 'Hard token cap on the classifier prompt. 0 means no cap.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_HEADERLESS_CHAR_LIMIT',
        label: 'Headerless character limit',
        hint: 'Character budget when a document has no page headers.',
        control: { kind: 'number', min: 0, suffix: 'chars' },
      },
      {
        key: 'CLASSIFY_DEFAULT_COUNTRY_TAG',
        label: 'Default country tag',
        hint: 'A country name always added to every classified document. Empty to skip.',
        control: { kind: 'text' },
      },
      {
        key: 'CLASSIFY_PERSON_FIELD_ID',
        label: 'Person custom-field ID',
        hint: 'A text custom field where the classifier stores the inferred person name.',
        control: { kind: 'number', min: 0 },
      },
    ],
  },
  {
    id: 'tags',
    title: 'Pipeline Tags',
    subtitle: 'The numeric tag IDs that drive document state. Set 0 to disable a tag.',
    fields: [
      {
        key: 'PRE_TAG_ID',
        label: 'OCR queue',
        hint: 'Documents tagged with this ID get picked up by the OCR daemon.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'POST_TAG_ID',
        label: 'OCR complete',
        hint: 'Tag applied after a successful OCR pass. Defaults to the classifier queue tag.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'OCR_PROCESSING_TAG_ID',
        label: 'OCR in-progress lock',
        hint: 'Optional. Needed only for multi-instance deployments to claim a document.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_PRE_TAG_ID',
        label: 'Classifier queue',
        hint: 'Tag marking documents that need classification. Defaults to OCR complete.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_POST_TAG_ID',
        label: 'Classification complete',
        hint: 'Optional tag applied after success. If unset, pipeline tags are simply removed.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'CLASSIFY_PROCESSING_TAG_ID',
        label: 'Classifier in-progress lock',
        hint: 'Optional. Multi-instance deployments use this to claim a document.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'ERROR_TAG_ID',
        label: 'Error tag',
        hint: 'Applied when OCR or classification fails. Pipeline tags are removed.',
        control: { kind: 'number', min: 0 },
      },
    ],
  },
  {
    id: 'perf',
    title: 'Performance',
    subtitle: 'Throughput and concurrency knobs.',
    fields: [
      {
        key: 'DOCUMENT_WORKERS',
        label: 'Document workers',
        hint: 'How many documents each daemon processes in parallel.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'PAGE_WORKERS',
        label: 'Page workers',
        hint: 'Pages OCR-d in parallel within a document. Drop to 1–2 on Ollama single-GPU.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'LLM_MAX_CONCURRENT',
        label: 'LLM max concurrent',
        hint: 'Global cap on LLM calls. 0 is unbounded.',
        control: { kind: 'number', min: 0 },
      },
      {
        key: 'POLL_INTERVAL',
        label: 'Poll interval',
        hint: 'Seconds between polling Paperless for new work.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
      {
        key: 'REQUEST_TIMEOUT',
        label: 'Request timeout',
        hint: 'HTTP timeout for model API calls.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
      {
        key: 'MAX_RETRIES',
        label: 'Max retries',
        hint: 'How many times a failing operation is retried before giving up.',
        control: { kind: 'number', min: 1 },
      },
      {
        key: 'MAX_RETRY_BACKOFF_SECONDS',
        label: 'Max retry backoff',
        hint: 'Upper bound on the exponential-backoff delay between retries.',
        control: { kind: 'number', min: 1, suffix: 's' },
      },
    ],
  },
  {
    id: 'logs',
    title: 'Logging',
    subtitle: 'What gets logged and how.',
    fields: [
      {
        key: 'LOG_LEVEL',
        label: 'Log level',
        hint: 'Minimum severity to emit.',
        control: {
          kind: 'segmented',
          options: [
            { value: 'DEBUG', label: 'DEBUG' },
            { value: 'INFO', label: 'INFO' },
            { value: 'WARNING', label: 'WARNING' },
            { value: 'ERROR', label: 'ERROR' },
          ],
        },
      },
      {
        key: 'LOG_FORMAT',
        label: 'Log format',
        hint: 'JSON when you ship logs to an aggregator; console for local debugging.',
        control: {
          kind: 'segmented',
          options: [
            { value: 'console', label: 'Console' },
            { value: 'json', label: 'JSON' },
          ],
        },
      },
    ],
  },
];

/** Every config key the model defines, flattened in display order. */
export function allFieldKeys(): string[] {
  return SETTINGS_SECTIONS.flatMap((section) =>
    section.fields.map((field) => field.key),
  );
}

/**
 * One parsed config value in the editable draft.
 *
 * The backend sends every value as a string; the screen parses each to its
 * real type for editing (a NumberStepper needs a number, a Toggle a boolean,
 * a list control a `string[]`) and serialises it back to a string to save.
 */
export type ConfigValue = string | number | boolean | string[];

/** The parsed draft — every config key mapped to its typed value. */
export type SettingsDraft = Record<string, ConfigValue>;

/** Look up a field descriptor by config key, or undefined if unknown. */
export function fieldByKey(key: string): SettingsField | undefined {
  for (const section of SETTINGS_SECTIONS) {
    const field = section.fields.find((f) => f.key === key);
    if (field) return field;
  }
  return undefined;
}

/**
 * Parse a wire string value to the typed value the field's control needs.
 *
 * Dispatches on the field's control kind: `number` → `number`, `toggle` →
 * `boolean`, `list` → `string[]` (comma-separated, trimmed), everything else
 * → the string unchanged. A `null` wire value (key on its coded default)
 * parses to the control's empty value, so an unedited field round-trips as
 * unchanged.
 */
export function parseValue(field: SettingsField, raw: string | null): ConfigValue {
  const kind = field.control.kind;
  if (kind === 'number') {
    const n = raw === null ? NaN : Number(raw);
    return Number.isFinite(n) ? n : 0;
  }
  if (kind === 'toggle') {
    return raw === 'true' || raw === 'True' || raw === '1';
  }
  if (kind === 'list') {
    if (raw === null || raw.trim() === '') return [];
    return raw.split(',').map((p) => p.trim()).filter((p) => p.length > 0);
  }
  return raw ?? '';
}

/**
 * Serialise a typed draft value back to the wire string the backend stores.
 *
 * The inverse of {@link parseValue}: a `string[]` joins with `, `, a boolean
 * becomes `'true'`/`'false'`, a number is stringified, a string passes
 * through. The config table is string-only, so the PUT body carries strings.
 */
export function serialiseValue(value: ConfigValue): string {
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}
