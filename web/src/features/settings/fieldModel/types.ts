/** Types for the Settings screen model: controls, fields, groups, sections and the draft. */

/**
 * A − / + numeric control. `step` defaults to 1; use a fraction like 0.01 for the [0, 1]
 * similarity-threshold fields.
 */
export interface NumberControl {
  kind: 'number';
  min: number;
  max?: number;
  step?: number;
  suffix?: string;
}

export interface TextControl {
  kind: 'text';
  mono?: boolean;
  placeholder?: string;
}

export interface SecretControl {
  kind: 'secret';
}

export interface ToggleControl {
  kind: 'toggle';
}

export interface SegmentedControl {
  kind: 'segmented';
  options: SegmentedOptionModel[];
}

/**
 * `disabledWhenEmpty` names a config key that must be non-empty for this option to be
 * selectable; it locks "Ollama" until `OLLAMA_BASE_URL` is set.
 */
export interface SegmentedOptionModel {
  value: string;
  label: string;
  disabledWhenEmpty?: string;
}

/**
 * A dropdown. With `reasoningKey` set, a compact "Reasoning" `Segmented` over
 * `reasoningOptions` renders beneath it, so a model and its reasoning effort share one row.
 */
export interface SelectControl {
  kind: 'select';
  options: { value: string; label: string }[];
  reasoningKey?: string;
  /** Required when `reasoningKey` is set. */
  reasoningOptions?: { value: string; label: string }[];
}

/** A comma-separated text field whose value is a `string[]`. */
export interface ListControl {
  kind: 'list';
}

/** Every control kind except the conditional wrapper. */
export type ConcreteControl =
  | NumberControl
  | TextControl
  | SecretControl
  | ToggleControl
  | SegmentedControl
  | SelectControl
  | ListControl;

/**
 * A control whose concrete kind depends on another field's draft value: the `variants` entry for
 * the `on` key's value, else `fallback`.
 */
export interface ConditionalControl {
  kind: 'conditional';
  on: string;
  variants: Record<string, ConcreteControl>;
  fallback: ConcreteControl;
}

export type FieldControl = ConcreteControl | ConditionalControl;

/** One editable configuration field. */
export interface SettingsField {
  /** A `Settings`-dataclass field name. */
  key: string;
  label: string;
  hint: string;
  control: FieldControl;
  /**
   * The screen masks the value and sends the key back only when changed. A `secret` control
   * always also has `secret: true`.
   */
  secret?: boolean;
  /**
   * Render only when another field's draft value matches, e.g. reasoning effort is OpenAI-only:
   * `{ key: 'OCR_PROVIDER', equals: 'openai' }`.
   */
  visibleWhen?: { key: string; equals: string };
}

/** A sub-card group, rendered as a `SettingsCard` inside its section's `SettingsBlock`. */
export interface SettingsGroup {
  /** Used as a React key and for group-action mapping. */
  id: string;
  title: string;
  subtitle?: string;
  fields: SettingsField[];
  /** Fields in a collapsed "Advanced" `Disclosure` beneath the primary fields. */
  advanced?: SettingsField[];
}

/** One section of the Settings screen — a `SettingsBlock` with sub-cards. */
export interface SettingsSection {
  /** Matches the SettingsSideNav Configuration item id. */
  id: string;
  title: string;
  /** Shown right-aligned beside the title. */
  subtitle: string;
  groups: SettingsGroup[];
}

/**
 * One parsed config value. The backend sends strings; the screen parses each to its real type
 * for editing and serialises it back to save.
 */
export type ConfigValue = string | number | boolean | string[];

export type SettingsDraft = Record<string, ConfigValue>;
