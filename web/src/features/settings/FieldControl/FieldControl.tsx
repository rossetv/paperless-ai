/**
 * The right-column control for one settings field, shared by SettingsSection and ConnectionsPanel.
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
  field: SettingsField;
  value: ConfigValue | undefined;
  /** The key is `field.key`, or `control.reasoningKey` for the companion reasoning segmented. */
  onChange: (key: string, value: ConfigValue | null) => void;
  /**
   * The id for the underlying input, for label association. Omit for controls that are not a
   * single labellable element (Segmented, SecretField).
   */
  controlId?: string;
  /**
   * The draft value for the companion reasoning-effort key; used only by a `select` with a
   * `reasoningKey`. Defaults to `''` (no selection).
   */
  reasoningValue?: ConfigValue;
}

/**
 * Renders the primitive matching `field.control.kind`. A `select` with a `reasoningKey` also
 * gets a companion "Reasoning" `Segmented` on a second line.
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

    case 'segmented': {
      // The environment may spell an option in another case; select it without rewriting the value.
      const current = typeof value === 'string' ? value : '';
      const match = control.options.find((o) => o.value.toLowerCase() === current.toLowerCase());
      return (
        <Segmented
          label={field.label}
          options={control.options}
          value={match?.value ?? current}
          onChange={(next) => onChange(field.key, next)}
        />
      );
    }

    case 'select': {
      // Destructured so TS narrows them without `!`: both are present exactly when there is a
      // non-empty reasoning option set.
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
