/**
 * Helper functions over the settings field model — key enumeration, field
 * look-up, and value parsing/serialisation.
 *
 * Tier: features/ — leaf module, no deps outside the settings feature.
 */

import type { ConfigValue, SettingsField } from './types';
import { SETTINGS_SECTIONS } from './sections';

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
