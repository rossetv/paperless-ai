/**
 * Helper functions over the settings field model — key enumeration, field
 * look-up, and value parsing/serialisation.
 *
 * Tier: features/ — leaf module, no deps outside the settings feature.
 */

import type { ConfigValue, SettingsField } from './types';
import { SETTINGS_SECTIONS } from './sections';

/** Every config key the model defines, flattened in display order. */
export function allFieldKeys(): string[] {
  return SETTINGS_SECTIONS.flatMap((section) =>
    section.groups.flatMap((group) => group.fields.map((field) => field.key)),
  );
}

/** Look up a field descriptor by config key, or undefined if unknown. */
export function fieldByKey(key: string): SettingsField | undefined {
  for (const section of SETTINGS_SECTIONS) {
    for (const group of section.groups) {
      const field = group.fields.find((f) => f.key === key);
      if (field) return field;
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
