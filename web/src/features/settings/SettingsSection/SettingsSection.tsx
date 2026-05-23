import React from 'react';
import { SectionCard } from '../../../components/primitives/SectionCard/SectionCard';
import { Row } from '../../../components/primitives/Row/Row';
import { SettingsTextField } from '../../../components/primitives/SettingsTextField/SettingsTextField';
import { SettingsSelectField } from '../../../components/primitives/SettingsSelectField/SettingsSelectField';
import { NumberStepper } from '../../../components/primitives/NumberStepper/NumberStepper';
import { Toggle } from '../../../components/primitives/Toggle/Toggle';
import { Segmented } from '../../../components/primitives/Segmented/Segmented';
import { SecretField } from '../SecretField/SecretField';
import type {
  ConfigValue,
  SettingsDraft,
  SettingsSection as SectionModel,
  SettingsField,
} from '../fieldModel';
import { parseValue, serialiseValue } from '../fieldModel';
import styles from './SettingsSection.module.css';

export interface SettingsSectionProps {
  /** The section descriptor from the field model. */
  section: SectionModel;
  /** The current draft values, keyed by config-key name. */
  values: SettingsDraft;
  /**
   * The config keys whose change requires a full document re-index — the
   * server's `requires_reindex` set. A field in this set shows a re-index
   * note under its hint.
   */
  reindexKeys?: ReadonlySet<string>;
  /**
   * Called when any field changes. For a secret key the value is the new
   * secret string, or `null` when the user is not replacing it.
   */
  onChange: (key: string, value: ConfigValue | null) => void;
  /** Optional extra content rendered inside the card, after the last row. */
  children?: React.ReactNode;
}

/**
 * Render the right-column control for one field, bound to its draft value.
 *
 * Each branch picks the primitive matching `field.control.kind`. The value is
 * read loosely from the draft and coerced to the type the control needs — the
 * field model guarantees the key's real type matches the kind. A `list`
 * control reuses the field model's `parseValue`/`serialiseValue` so the
 * draft holds a `string[]` while the text input shows a comma-joined string.
 */
function FieldControl({
  field,
  value,
  onChange,
}: {
  field: SettingsField;
  value: ConfigValue | undefined;
  onChange: (value: ConfigValue | null) => void;
}): React.ReactElement {
  const control = field.control;
  const id = `setting-${field.key}`;

  switch (control.kind) {
    case 'number':
      return (
        <NumberStepper
          label={field.label}
          value={typeof value === 'number' ? value : 0}
          min={control.min}
          max={control.max}
          suffix={control.suffix}
          onChange={(next) => onChange(next)}
        />
      );
    case 'toggle':
      return (
        <Toggle
          label={field.label}
          checked={value === true}
          onChange={(next) => onChange(next)}
        />
      );
    case 'segmented':
      return (
        <Segmented
          label={field.label}
          options={control.options}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(next)}
        />
      );
    case 'select':
      return (
        <SettingsSelectField
          id={id}
          label={field.label}
          options={control.options}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(next)}
        />
      );
    case 'secret':
      return (
        <SecretField
          id={id}
          label={field.label}
          maskedValue={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(next)}
        />
      );
    case 'list':
      return (
        <SettingsTextField
          id={id}
          label={field.label}
          mono
          value={Array.isArray(value) ? serialiseValue(value) : ''}
          onChange={(raw) => onChange(parseValue(field, raw))}
        />
      );
    case 'text':
    default:
      return (
        <SettingsTextField
          id={id}
          label={field.label}
          mono={control.kind === 'text' ? control.mono : false}
          placeholder={control.kind === 'text' ? control.placeholder : undefined}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(next)}
        />
      );
  }
}

/**
 * One settings section — a `SectionCard` of model-driven field rows.
 *
 * Renders every field of the given `section`, dispatching on the field's
 * control kind to the matching primitive and binding it to the draft value.
 * The `Row.controlId` is set for single-element controls so the label
 * focuses the control; Segmented and SecretField rows omit it (they are not
 * a single labellable element). A field whose key is in `reindexKeys` gets a
 * re-index note appended to its hint — there is no restart concept; the only
 * operator-facing consequence of a change is whether a re-index is needed.
 *
 * Tier: features/ — knows the field model, composes primitives + SecretField.
 */
export function SettingsSection({
  section,
  values,
  reindexKeys,
  onChange,
  children,
}: SettingsSectionProps): React.ReactElement {
  return (
    <SectionCard id={section.id} title={section.title} subtitle={section.subtitle}>
      {section.fields.map((field, index) => {
        // A single-element control can be focused from its label; a Segmented
        // group or a SecretField (multiple elements) cannot.
        const labellable =
          field.control.kind !== 'segmented' && field.control.kind !== 'secret';
        const needsReindex = reindexKeys?.has(field.key) ?? false;
        const hint = needsReindex ? (
          <>
            {field.hint}
            <span className={styles['reindexNote']}>
              {' '}
              Changing this requires re-indexing all documents — run a full
              rebuild from the Index page.
            </span>
          </>
        ) : (
          field.hint
        );
        return (
          <Row
            key={field.key}
            label={field.label}
            hint={hint}
            env={field.key}
            controlId={labellable ? `setting-${field.key}` : undefined}
            last={index === section.fields.length - 1 && children === undefined}
          >
            <FieldControl
              field={field}
              value={values[field.key]}
              onChange={(next) => onChange(field.key, next)}
            />
          </Row>
        );
      })}
      {children}
    </SectionCard>
  );
}
