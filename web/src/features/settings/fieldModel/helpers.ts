/**
 * Helper functions over the settings field model — key enumeration, field
 * look-up, and value parsing/serialisation.
 *
 * Tier: features/ — leaf module, no deps outside the settings feature.
 */

import type { ConditionalControl, ConfigValue, SettingsField } from './types';
import {
  MODEL_OPTIONS,
  PROVIDER_OPTIONS,
  REASONING_EFFORT_OPTIONS,
  SETTINGS_SECTIONS,
} from './sections';

/**
 * The three rows for one Search sub-step (Planner / Judge / Answer): its
 * provider, its model (an OpenAI dropdown or a free-text Ollama model, keyed on
 * that sub-step's provider), and its reasoning effort (shown only on OpenAI).
 * Each sub-step chooses its provider and model independently — mix freely, e.g.
 * a local judge with a cloud answer.
 *
 * Lives here (not in `sections.ts`) so that file stays a logic-free pure-data
 * literal under §3.1 (FE-06); the option lists it spreads are imported back
 * from `sections.ts`, which holds the shared declarative data.
 */
export function searchStageFields(stage: {
  key: 'PLANNER' | 'JUDGE' | 'ANSWER';
  label: string;
  hint: string;
  ollamaPlaceholder: string;
}): SettingsField[] {
  const provider = `SEARCH_${stage.key}_PROVIDER`;
  return [
    {
      key: provider,
      label: `${stage.label} provider`,
      hint: stage.hint,
      control: { kind: 'segmented', options: PROVIDER_OPTIONS },
    },
    {
      key: `SEARCH_${stage.key}_MODEL`,
      label: `${stage.label} model`,
      hint: 'OpenAI: pick a model. Ollama: type a pulled model.',
      // A dropdown of the OpenAI models when this sub-step is on OpenAI; a
      // free-text field for an Ollama model otherwise.
      control: {
        kind: 'conditional',
        on: provider,
        variants: { openai: { kind: 'select', options: MODEL_OPTIONS } },
        fallback: { kind: 'text', mono: true, placeholder: stage.ollamaPlaceholder },
      },
    },
    {
      key: `SEARCH_${stage.key}_REASONING_EFFORT`,
      label: `${stage.label} reasoning effort`,
      hint: 'Higher tiers spend more reasoning tokens. OpenAI only.',
      control: { kind: 'segmented', options: REASONING_EFFORT_OPTIONS },
      visibleWhen: { key: provider, equals: 'openai' },
    },
  ];
}

/**
 * Every config key the model defines, flattened in display order.
 *
 * Includes keys from both `group.fields` and `group.advanced` (when present).
 * For any `select` field that carries a `reasoningKey`, that sub-key is also
 * included so `useUnsavedSettings` seeds and serialises it correctly.
 */
export function allFieldKeys(): string[] {
  return SETTINGS_SECTIONS.flatMap((section) =>
    section.groups.flatMap((group) => {
      const allFields = [...group.fields, ...(group.advanced ?? [])];
      return allFields.flatMap((field) => {
        const keys: string[] = [field.key];
        if (
          field.control.kind === 'select' &&
          field.control.reasoningKey !== undefined
        ) {
          keys.push(field.control.reasoningKey);
        }
        return keys;
      });
    }),
  );
}

/**
 * Look up a field descriptor by config key, or `undefined` if unknown.
 *
 * Searches `group.fields` and `group.advanced` across every section.
 * If the key is not a direct field key but matches the `reasoningKey` of a
 * `select` control, returns a synthetic `SettingsField` with a `segmented`
 * control over `reasoningOptions` — so `parseValue` treats it as a string
 * and `toDraft` seeds it from the draft.
 */
export function fieldByKey(key: string): SettingsField | undefined {
  for (const section of SETTINGS_SECTIONS) {
    for (const group of section.groups) {
      const allFields = [...group.fields, ...(group.advanced ?? [])];

      // Direct match first.
      const direct = allFields.find((f) => f.key === key);
      if (direct) return direct;

      // Synthetic match: a select whose reasoningKey === key.
      for (const field of allFields) {
        if (
          field.control.kind === 'select' &&
          field.control.reasoningKey === key
        ) {
          const syntheticField: SettingsField = {
            key,
            label: 'Reasoning',
            hint: '',
            control: {
              kind: 'segmented',
              options: field.control.reasoningOptions ?? [],
            },
          };
          return syntheticField;
        }
      }
    }
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
  const control = field.control;
  if (control.kind === 'number') {
    const n = raw === null ? NaN : Number(raw);
    return Number.isFinite(n) ? n : 0;
  }
  if (control.kind === 'toggle') {
    return raw === 'true' || raw === 'True' || raw === '1';
  }
  if (control.kind === 'list') {
    if (raw === null || raw.trim() === '') return [];
    return raw.split(',').map((p) => p.trim()).filter((p) => p.length > 0);
  }
  // A `conditional` control parses by the kind it resolves to. Every conditional
  // in the model today resolves only to string-typed controls (select/text), so
  // the string parse below is correct — but assert that invariant rather than
  // letting a future number/list/toggle variant silently mis-parse as a string
  // and break dirty-tracking (FE-66).
  if (control.kind === 'conditional') {
    assertConditionalIsStringTyped(field.key, control);
  }
  return raw ?? '';
}

/** Control kinds whose parsed value is a plain string (so a `conditional`
 *  resolving only to these is safely string-parsed by {@link parseValue}). */
const STRING_CONTROL_KINDS: ReadonlySet<string> = new Set([
  'text',
  'select',
  'secret',
]);

/**
 * Assert every variant and the fallback of a conditional control resolve to a
 * string-typed control. {@link parseValue} parses a conditional as a string;
 * this guards the invariant that lets it. Throws (model authoring error) the
 * moment a conditional wraps a number/list/toggle variant — better a loud
 * failure than a silently mis-typed baseline.
 */
function assertConditionalIsStringTyped(
  key: string,
  control: ConditionalControl,
): void {
  const resolved = [control.fallback, ...Object.values(control.variants)];
  for (const variant of resolved) {
    if (!STRING_CONTROL_KINDS.has(variant.kind)) {
      throw new Error(
        `Conditional control for "${key}" resolves to a non-string control ` +
          `("${variant.kind}"); parseValue only supports string-typed ` +
          `conditional variants. Add explicit parsing if this is intended.`,
      );
    }
  }
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
