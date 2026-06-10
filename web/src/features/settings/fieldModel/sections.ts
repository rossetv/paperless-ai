/**
 * The seven settings sections, in pipeline display order.
 *
 * Each section contains one or more named sub-card groups, each group
 * containing an ordered list of field descriptors bound to one config key.
 * Groups may also carry an `advanced` array rendered inside a collapsed
 * "Advanced" disclosure beneath the primary fields.
 *
 * SelectControl fields may carry `reasoningKey`/`reasoningOptions` to render
 * a companion reasoning-effort segmented line beneath the model select.
 *
 * Adding or retiring a config key is a change to this file alone — the
 * screen components are generic.
 *
 * Tier: features/ — leaf module, no deps outside the settings feature.
 */

import type { SettingsSection } from './types';

// ---------------------------------------------------------------------------
// Shared option lists
// ---------------------------------------------------------------------------

/** A small fixed model-identifier list, reused by the planner/answer/judge selects. */
const MODEL_OPTIONS = [
  { value: 'gpt-5.4-nano', label: 'gpt-5.4-nano' },
  { value: 'gpt-5.4-mini', label: 'gpt-5.4-mini' },
  { value: 'gpt-5.4', label: 'gpt-5.4' },
  { value: 'gpt-5.5', label: 'gpt-5.5' },
  { value: 'o4-mini', label: 'o4-mini' },
];

const EMBEDDING_MODEL_OPTIONS = [
  { value: 'text-embedding-3-small', label: 'text-embedding-3-small' },
  { value: 'text-embedding-3-large', label: 'text-embedding-3-large' },
];

/**
 * OpenAI reasoning-effort tiers (the SDK's `ReasoningEffort` literal). Higher
 * tiers spend more reasoning tokens for better quality; OpenAI-only — the value
 * is ignored when the provider is Ollama. Reused by the OCR, classifier, and
 * search planner/answer/judge reasoning selects.
 */
const REASONING_EFFORT_OPTIONS = [
  { value: 'minimal', label: 'Minimal' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];

// ---------------------------------------------------------------------------
// SETTINGS_SECTIONS — the ordered declarative model for the Settings screen
// ---------------------------------------------------------------------------

/**
 * The seven settings sections, in pipeline display order.
 *
 * The order and section ids match the SettingsSideNav Pipeline / Operations
 * groups. Each section contains one or more named groups (sub-cards). Field
 * order within a group follows the approved settings-redesign mock.
 */
export const SETTINGS_SECTIONS: SettingsSection[] = [
  // ── 1. Connections ────────────────────────────────────────────────────────
  {
    id: 'connections',
    title: 'Connections',
    subtitle: 'External services this app talks to.',
    groups: [
      {
        id: 'provider',
        title: 'AI provider',
        subtitle: 'OpenAI is hosted; Ollama runs locally. Embeddings always use OpenAI.',
        fields: [
          {
            key: 'LLM_PROVIDER',
            label: 'LLM provider',
            hint: 'Switches which credentials matter below.',
            control: {
              kind: 'segmented',
              options: [
                { value: 'openai', label: 'OpenAI' },
                { value: 'ollama', label: 'Ollama' },
              ],
            },
          },
        ],
      },
      {
        id: 'paperless',
        title: 'Paperless-ngx',
        subtitle: 'Where the daemons reach Paperless, and where the browser opens documents.',
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
        id: 'openai',
        title: 'OpenAI',
        subtitle: 'Required for every process — embeddings always go through OpenAI.',
        fields: [
          {
            key: 'OPENAI_API_KEY',
            label: 'OpenAI API key',
            hint: 'Required for every process — embeddings always go through OpenAI.',
            control: { kind: 'secret' },
            secret: true,
          },
        ],
      },
      {
        id: 'ollama',
        title: 'Ollama',
        subtitle: 'Ignored when the provider is OpenAI.',
        fields: [
          {
            key: 'OLLAMA_BASE_URL',
            label: 'Ollama base URL',
            hint: 'Must end with /v1/. Ignored when the provider is OpenAI.',
            control: { kind: 'text', mono: true, placeholder: 'http://ollama.lan:11434/v1/' },
          },
        ],
      },
    ],
  },

  // ── 2. OCR ────────────────────────────────────────────────────────────────
  {
    id: 'ocr',
    title: 'OCR',
    subtitle: 'Vision-model transcription of scanned pages.',
    groups: [
      {
        id: 'model',
        title: 'Model',
        subtitle: 'Tried in order; first success wins. Higher reasoning tiers cost more tokens (OpenAI only).',
        fields: [
          {
            key: 'OCR_MODELS',
            label: 'Model fallback chain',
            hint: 'Comma-separated identifiers tried in order until one accepts the request.',
            control: { kind: 'list' },
          },
          {
            key: 'OCR_REASONING_EFFORT',
            label: 'Reasoning effort',
            hint: 'minimal / low / medium / high. Ignored for non-OpenAI providers.',
            control: { kind: 'segmented', options: REASONING_EFFORT_OPTIONS },
          },
        ],
      },
      {
        id: 'imaging',
        title: 'Imaging & throughput',
        subtitle: 'Resolution, image size, and page-level parallelism.',
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
            key: 'PAGE_WORKERS',
            label: 'Page workers',
            hint: 'Pages OCR-d in parallel within a document. Drop to 1–2 on Ollama single-GPU.',
            control: { kind: 'number', min: 1 },
          },
        ],
        advanced: [
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
    ],
  },

  // ── 3. Classification ─────────────────────────────────────────────────────
  {
    id: 'classification',
    title: 'Classification',
    subtitle: 'Metadata enrichment — title, correspondent, type, tags.',
    groups: [
      {
        id: 'model',
        title: 'Model',
        subtitle: 'Tried in order; first success wins. Higher reasoning tiers cost more tokens (OpenAI only).',
        fields: [
          {
            key: 'CLASSIFY_MODELS',
            label: 'Model fallback chain',
            hint: 'Comma-separated identifiers tried in order until one accepts the request.',
            control: { kind: 'list' },
          },
          {
            key: 'CLASSIFY_REASONING_EFFORT',
            label: 'Reasoning effort',
            hint: 'minimal / low / medium / high. Ignored for non-OpenAI providers.',
            control: { kind: 'segmented', options: REASONING_EFFORT_OPTIONS },
          },
        ],
      },
      {
        id: 'tagging',
        title: 'Tagging',
        subtitle: 'Limits and taxonomy context for classification output.',
        fields: [
          {
            key: 'CLASSIFY_TAG_LIMIT',
            label: 'Tag limit',
            hint: 'Max optional tags to keep. Required tags (year, country) do not count.',
            control: { kind: 'number', min: 0 },
          },
          {
            key: 'CLASSIFY_DEFAULT_COUNTRY_TAG',
            label: 'Default country tag',
            hint: 'A country name always added to every classified document. Empty to skip.',
            control: { kind: 'text' },
          },
        ],
        advanced: [
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
            key: 'CLASSIFY_TAXONOMY_LIMIT',
            label: 'Taxonomy context limit',
            hint: 'Max correspondents / types / tags included in the LLM prompt as context.',
            control: { kind: 'number', min: 0 },
          },
          {
            key: 'CLASSIFY_PERSON_FIELD_ID',
            label: 'Person custom-field ID',
            hint: 'A text custom field where the classifier stores the inferred person name.',
            control: { kind: 'number', min: 0 },
          },
        ],
      },
    ],
  },

  // ── 4. Indexing ───────────────────────────────────────────────────────────
  {
    id: 'indexing',
    title: 'Indexing',
    subtitle: 'How the indexer chunks, embeds and reconciles your library.',
    groups: [
      {
        id: 'embeddings',
        title: 'Embeddings',
        subtitle: 'Changing the model or dimensions triggers a full rebuild.',
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
        ],
      },
      {
        id: 'chunking',
        title: 'Chunking & schedule',
        subtitle: 'How long each text chunk is, how much overlap, and when the indexer runs.',
        fields: [
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
        ],
        advanced: [
          {
            key: 'DELETION_SWEEP_INTERVAL',
            label: 'Deletion sweep interval',
            hint: 'Seconds between full deletion sweeps.',
            control: { kind: 'number', min: 1, suffix: 's' },
          },
          {
            key: 'EMBEDDING_MAX_CONCURRENT',
            label: 'Embedding max concurrent',
            hint: 'Global cap on concurrent embedding calls. 0 is unbounded.',
            control: { kind: 'number', min: 0 },
          },
        ],
      },
    ],
  },

  // ── 5. Search ─────────────────────────────────────────────────────────────
  {
    id: 'search',
    title: 'Search',
    subtitle: 'Tune the agentic search pipeline — planning, retrieval, synthesis.',
    groups: [
      {
        id: 'models',
        title: 'Models',
        subtitle: 'The planner does structured-query extraction; the answer model writes the prose.',
        fields: [
          {
            key: 'SEARCH_PLANNER_MODEL',
            label: 'Planner model',
            hint: 'Cheaper model for structured query extraction.',
            control: {
              kind: 'select',
              options: MODEL_OPTIONS,
              reasoningKey: 'SEARCH_PLANNER_REASONING_EFFORT',
              reasoningOptions: REASONING_EFFORT_OPTIONS,
            },
          },
          {
            key: 'SEARCH_ANSWER_MODEL',
            label: 'Answer model',
            hint: 'Stronger model for user-facing synthesis.',
            control: {
              kind: 'select',
              options: MODEL_OPTIONS,
              reasoningKey: 'SEARCH_ANSWER_REASONING_EFFORT',
              reasoningOptions: REASONING_EFFORT_OPTIONS,
            },
          },
          {
            key: 'SEARCH_JUDGE_MODEL',
            label: 'Judge model',
            hint: 'The model that screens retrieved documents. Defaults to the planner model.',
            control: {
              kind: 'select',
              options: MODEL_OPTIONS,
              reasoningKey: 'SEARCH_JUDGE_REASONING_EFFORT',
              reasoningOptions: REASONING_EFFORT_OPTIONS,
            },
          },
        ],
      },
      {
        id: 'retrieval',
        title: 'Retrieval & relevance',
        subtitle:
          'How many documents the synthesiser sees and how results are gated and tiered.',
        fields: [
          {
            key: 'SEARCH_TOP_K',
            label: 'Top K',
            hint: 'How many documents are fed to the synthesiser.',
            control: { kind: 'number', min: 1 },
          },
          {
            key: 'SEARCH_RELEVANCE_MIN_SIMILARITY',
            label: 'Gate floor',
            hint: 'Results whose best similarity falls below this — and that have no keyword hit — are rejected as "no matches" before synthesis. 0 shows everything; default 0.60.',
            control: { kind: 'number', min: 0, max: 1, step: 0.01 },
          },
          {
            key: 'SEARCH_RELEVANCE_TIER_STRONG',
            label: 'Strong match ≥',
            hint: 'A shown result at or above this similarity badges "Strong match". Default 0.70.',
            control: { kind: 'number', min: 0, max: 1, step: 0.01 },
          },
        ],
      },
      {
        id: 'behaviour',
        title: 'Behaviour',
        subtitle: 'Judge gating and identity-aware resolution.',
        fields: [
          {
            key: 'SEARCH_GATE_JUDGE',
            label: 'Enable judge',
            hint: 'Screen documents on the cheap judge model before the expensive answer model. Default on.',
            control: { kind: 'toggle' },
          },
          {
            key: 'SEARCH_IDENTITY_AWARE',
            label: 'Identity-aware search',
            hint: 'Resolve first-person references to the signed-in user\'s display name. Requires the account to have a display name set. Default on.',
            control: { kind: 'toggle' },
          },
        ],
        advanced: [
          {
            key: 'SEARCH_MAX_REFINEMENTS',
            label: 'Max refinements',
            hint: 'Agentic refinement passes. Each adds one LLM call per query, so cost and latency scale with it. No hard cap; default 1.',
            control: { kind: 'number', min: 0 },
          },
          {
            key: 'SEARCH_RELEVANCE_TIER_GOOD',
            label: 'Good match ≥',
            hint: 'Badges "Good match" at or above this. Must sit between the Partial and Strong cut-points. Default 0.66.',
            control: { kind: 'number', min: 0, max: 1, step: 0.01 },
          },
          {
            key: 'SEARCH_RELEVANCE_TIER_PARTIAL',
            label: 'Partial match ≥',
            hint: 'Badges "Partial match" at or above this; anything lower badges "Weak match". Default 0.60.',
            control: { kind: 'number', min: 0, max: 1, step: 0.01 },
          },
          {
            key: 'SEARCH_JUDGE_RATIONALES',
            label: 'Judge rationales',
            hint: 'Have the relevance judge write a one-line reason per document. Costs a few extra tokens per query; turn off to save them.',
            control: { kind: 'toggle' },
          },
          {
            key: 'SEARCH_SERVER_HOST',
            label: 'Server host',
            hint: '0.0.0.0 binds all interfaces.',
            control: { kind: 'text', mono: true },
          },
          {
            key: 'SEARCH_SERVER_PORT',
            label: 'Server port',
            hint: 'The TCP port the search server listens on.',
            control: { kind: 'number', min: 1, max: 65535 },
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
        ],
      },
    ],
  },

  // ── 6. Automation & Daemons ───────────────────────────────────────────────
  {
    id: 'automation',
    title: 'Automation & Daemons',
    subtitle: 'Pipeline tag IDs, worker concurrency, and polling behaviour.',
    groups: [
      {
        id: 'tags',
        title: 'Pipeline tags',
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
            key: 'ERROR_TAG_ID',
            label: 'Error tag',
            hint: 'Applied when OCR or classification fails. Pipeline tags are removed.',
            control: { kind: 'number', min: 0 },
          },
        ],
      },
      {
        id: 'workers',
        title: 'Workers & polling',
        subtitle: 'Parallelism within each daemon and how often they check for work.',
        fields: [
          {
            key: 'DOCUMENT_WORKERS',
            label: 'Document workers',
            hint: 'How many documents each daemon processes in parallel.',
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
        ],
        advanced: [
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
            key: 'OCR_PROCESSING_TAG_ID',
            label: 'OCR in-progress lock',
            hint: 'Optional. Needed only for multi-instance deployments to claim a document.',
            control: { kind: 'number', min: 0 },
          },
          {
            key: 'CLASSIFY_PROCESSING_TAG_ID',
            label: 'Classifier in-progress lock',
            hint: 'Optional. Multi-instance deployments use this to claim a document.',
            control: { kind: 'number', min: 0 },
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
    ],
  },

  // ── 7. Logging ────────────────────────────────────────────────────────────
  {
    id: 'logging',
    title: 'Logging',
    subtitle: 'What gets logged and how.',
    groups: [
      {
        id: 'output',
        title: 'Output',
        subtitle: 'Severity threshold and emit format.',
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
    ],
  },
];
