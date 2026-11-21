/** Helpers over the settings field model: key enumeration, field look-up, value parsing. */

import type { ConditionalControl, ConfigValue, SettingsField } from './types';
import {
  MODEL_OPTIONS,
  PROVIDER_OPTIONS,
  REASONING_EFFORT_OPTIONS,
  SETTINGS_SECTIONS,
} from './sections';

/**
 * The provider, model and reasoning-effort rows for one Search sub-step (Planner / Judge /
 * Answer). Each sub-step picks its provider and model independently, e.g. a local judge with a
 * cloud answer.
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
 * Every config key the model defines, in display order, including advanced fields and each
 * select's `reasoningKey` (so `useUnsavedSettings` seeds and serialises it).
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
 * A select's `reasoningKey` yields a synthetic `segmented` field over `reasoningOptions`, so
 * `parseValue` treats it as a string and `toDraft` seeds it.
 */
export function fieldByKey(key: string): SettingsField | undefined {
  for (const section of SETTINGS_SECTIONS) {
    for (const group of section.groups) {
      const allFields = [...group.fields, ...(group.advanced ?? [])];

      const direct = allFields.find((f) => f.key === key);
      if (direct) return direct;

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
 * Parse a wire string to the typed value the field's control needs. A `null` wire value parses
 * to the control's empty value, so an unedited field round-trips as unchanged.
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
  // Every conditional resolves only to string-typed controls, so it parses as a string. Assert
  // that, so a number/list/toggle variant cannot silently mis-parse and break dirty-tracking.
  if (control.kind === 'conditional') {
    assertConditionalIsStringTyped(field.key, control);
  }
  return raw ?? '';
}

const STRING_CONTROL_KINDS: ReadonlySet<string> = new Set([
  'text',
  'select',
  'secret',
]);

/** Throws (a model authoring error) if any variant or the fallback is not string-typed. */
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

/** The inverse of {@link parseValue}: the config table stores only strings. */
export function serialiseValue(value: ConfigValue): string {
  if (Array.isArray(value)) return value.join(', ');
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}
