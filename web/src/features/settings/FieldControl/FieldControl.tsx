/**
 * FieldControl — renders the right-column control for one settings field.
 *
 * Extracted from SettingsSection so that other panels (e.g. ConnectionsPanel)
 * can reuse the same dispatch without duplicating the switch statement.
 *
 * For a `select` field with a `reasoningKey`, the component renders the
 * `SettingsSelectField` as normal, then a second line — a compact "Reasoning"
 * `Segmented` whose value comes from `reasoningValue` and whose onChange calls
 * `onChange(control.reasoningKey, v)`.
 *
 * Tier: features/settings — knows the field model, composes primitives + SecretField.
 */

import React from 'react';
import { SettingsTextField } from '../../../components/primitives/SettingsTextField/SettingsTextField';
import { SettingsListField } from '../../../components/primitives/SettingsListField/SettingsListField';
import { SettingsSelectField } from '../../../components/primitives/SettingsSelectField/SettingsSelectField';
import { NumberStepper } from '../../../components/primitives/NumberStepper/NumberStepper';
import { Toggle } from '../../../components/primitives/Toggle/Toggle';
import { Segmented } from '../../../components/primitives/Segmented/Segmented';
import { SecretField } from '../SecretField/SecretField';
import type { ConfigValue, SettingsField } from '../fieldModel';
import styles from './FieldControl.module.css';

export interface FieldControlProps {
  /** The field descriptor from the field model. */
  field: SettingsField;
  /** The current draft value for this field's key. */
  value: ConfigValue | undefined;
  /**
   * Called when the field's value changes. The key is always `field.key`,
   * except for the companion reasoning segmented — in that case the key is
   * `control.reasoningKey`.
   */
  onChange: (key: string, value: ConfigValue | null) => void;
  /**
   * The id to set on the underlying input element (for label association).
   * Omit for controls that are not a single labellable element (Segmented,
   * SecretField).
   */
  controlId?: string;
  /**
   * The current draft value for the companion reasoning-effort key.
   * Only used when `field.control.kind === 'select'` and `control.reasoningKey`
   * is set. Defaults to `''` (no selection) when omitted.
   */
  reasoningValue?: ConfigValue;
}

/**
 * Dispatch on `field.control.kind` and render the matching primitive.
 *
 * For a `select` control with a `reasoningKey`, renders the select plus a
 * companion "Reasoning" `Segmented` on a second line, bound to
 * `reasoningValue` / `onChange(control.reasoningKey, v)`.
 */
export function FieldControl({
  field,
  value,
  onChange,
  controlId,
  reasoningValue,
}: FieldControlProps): React.ReactElement {
  const control = field.control;

  switch (control.kind) {
    case 'number':
      return (
        <NumberStepper
          label={field.label}
          value={typeof value === 'number' ? value : 0}
          min={control.min}
          {...(control.max !== undefined ? { max: control.max } : {})}
          {...(control.step !== undefined ? { step: control.step } : {})}
          {...(control.suffix !== undefined ? { suffix: control.suffix } : {})}
          onChange={(next) => onChange(field.key, next)}
        />
      );

    case 'toggle':
      return (
        <Toggle
          label={field.label}
          checked={value === true}
          onChange={(next) => onChange(field.key, next)}
        />
      );

    case 'segmented':
      return (
        <Segmented
          label={field.label}
          options={control.options}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(field.key, next)}
        />
      );

    case 'select': {
      // Destructure the guarded values so TS narrows them without `!` (FE-54):
      // both are present exactly when there is a non-empty reasoning option set.
      const { reasoningKey, reasoningOptions } = control;
      const reasoning =
        reasoningKey !== undefined && (reasoningOptions?.length ?? 0) > 0
          ? { key: reasoningKey, options: reasoningOptions ?? [] }
          : null;

      return (
        <div className={styles['composite']}>
          <SettingsSelectField
            id={controlId ?? `setting-${field.key}`}
            label={field.label}
            options={control.options}
            value={typeof value === 'string' ? value : ''}
            onChange={(next) => onChange(field.key, next)}
          />
          {reasoning !== null && (
            <Segmented
              label="Reasoning"
              options={reasoning.options}
              value={typeof reasoningValue === 'string' ? reasoningValue : ''}
              onChange={(next) => onChange(reasoning.key, next)}
            />
          )}
        </div>
      );
    }

    case 'secret':
      return (
        <SecretField
          id={controlId ?? `setting-${field.key}`}
          label={field.label}
          maskedValue={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(field.key, next)}
        />
      );

    case 'list':
      return (
        <SettingsListField
          id={controlId ?? `setting-${field.key}`}
          label={field.label}
          value={Array.isArray(value) ? value : []}
          onChange={(next) => onChange(field.key, next)}
        />
      );

    case 'text':
    default: {
      const textMono = control.kind === 'text' ? (control.mono ?? false) : false;
      const textPlaceholder = control.kind === 'text' ? control.placeholder : undefined;
      return (
        <SettingsTextField
          id={controlId ?? `setting-${field.key}`}
          label={field.label}
          {...(textMono ? { mono: true } : {})}
          {...(textPlaceholder !== undefined ? { placeholder: textPlaceholder } : {})}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(field.key, next)}
        />
      );
    }
  }
}
