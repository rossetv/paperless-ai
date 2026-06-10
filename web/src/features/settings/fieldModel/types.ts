/**
 * Control, field, group, and section interfaces for the Settings screen model.
 *
 * Also exports the `ConfigValue` and `SettingsDraft` types used by the
 * draft-state machinery in `useUnsavedSettings`.
 *
 * Tier: features/ — leaf module, no deps outside the settings feature.
 */

// ---------------------------------------------------------------------------
// Control kinds
// ---------------------------------------------------------------------------

/**
 * A − / + numeric control. `min`/`max` clamp; `suffix` is an optional unit;
 * `step` is the − / + increment (defaults to 1 — set a fraction like 0.01 for
 * the [0, 1] similarity-threshold fields).
 */
export interface NumberControl {
  kind: 'number';
  min: number;
  max?: number;
  step?: number;
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

/**
 * A dropdown over a fixed option set.
 *
 * When `reasoningKey` is set, SettingsSection renders a second line beneath
 * the select: a compact `Segmented` whose `value` comes from `reasoningKey`
 * in the draft and whose options are `reasoningOptions`. This lets a model
 * select and its reasoning-effort control share one visual unit without
 * duplicating rows.
 */
export interface SelectControl {
  kind: 'select';
  options: { value: string; label: string }[];
  /**
   * The config key for the companion reasoning-effort segmented control.
   * When present, a "Reasoning" segmented is rendered immediately beneath
   * the select using `reasoningOptions`.
   */
  reasoningKey?: string;
  /**
   * The option list for the companion reasoning-effort segmented control.
   * Required when `reasoningKey` is set; ignored otherwise.
   */
  reasoningOptions?: { value: string; label: string }[];
}

/**
 * A comma-separated list control — an editable text field whose value is a
 * `string[]`. Used for OCR_MODELS, CLASSIFY_MODELS and OCR_REFUSAL_MARKERS.
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

// ---------------------------------------------------------------------------
// Field, group, section
// ---------------------------------------------------------------------------

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

/**
 * A named sub-card group within a settings section.
 *
 * Each group renders as a `SettingsCard` inside its parent `SettingsBlock`.
 * The `id` is used as a React key; `title` and `subtitle` are passed to the
 * card header.
 */
export interface SettingsGroup {
  /** Stable identifier — used as a React key and for group-action mapping. */
  id: string;
  /** The sub-card heading. */
  title: string;
  /** Optional sub-card subtitle shown under the heading. */
  subtitle?: string;
  /** The fields in this group, top to bottom. */
  fields: SettingsField[];
  /**
   * Fields shown inside a collapsed "Advanced" `Disclosure` beneath the
   * primary fields. Collapsed by default. Omit (or leave empty) when all
   * fields belong in the primary list.
   */
  advanced?: SettingsField[];
}

/** One section of the Settings screen — a `SettingsBlock` with sub-cards. */
export interface SettingsSection {
  /** Stable anchor id — matches the SettingsSideNav Configuration item id. */
  id: string;
  /** The section title. */
  title: string;
  /** The section subtitle, shown right-aligned beside the title. */
  subtitle: string;
  /** The sub-card groups, top to bottom. */
  groups: SettingsGroup[];
}

// ---------------------------------------------------------------------------
// Draft state types
// ---------------------------------------------------------------------------

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
