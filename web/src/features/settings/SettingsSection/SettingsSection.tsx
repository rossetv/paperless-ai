import React from 'react';
import { SettingsBlock } from '../../../components/primitives/SettingsBlock/SettingsBlock';
import { SettingsCard } from '../../../components/primitives/SettingsCard/SettingsCard';
import { Row } from '../../../components/primitives/Row/Row';
import { SettingsTextField } from '../../../components/primitives/SettingsTextField/SettingsTextField';
import { SettingsListField } from '../../../components/primitives/SettingsListField/SettingsListField';
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
   * The config keys whose value is currently on the coded default. A field in
   * this set shows a subtle "default" badge so the operator can tell a coded
   * default from an explicit override.
   */
  defaultKeys?: ReadonlySet<string>;
  /**
   * Called when any field changes. For a secret key the value is the new
   * secret string, or `null` when the user is not replacing it.
   */
  onChange: (key: string, value: ConfigValue | null) => void;
  /**
   * Map from group id to a React node to render in that group's card header
   * actions slot. Used by the `paperless/endpoint` group for the
   * `TestConnectionAction`.
   */
  groupActions?: Record<string, React.ReactNode>;
}

/**
 * Render the right-column control for one field, bound to its draft value.
 *
 * Each branch picks the primitive matching `field.control.kind`.
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
          {...(control.max !== undefined ? { max: control.max } : {})}
          {...(control.suffix !== undefined ? { suffix: control.suffix } : {})}
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
        <SettingsListField
          id={id}
          label={field.label}
          value={Array.isArray(value) ? value : []}
          onChange={(next) => onChange(next)}
        />
      );
    case 'text':
    default: {
      const textMono = control.kind === 'text' ? (control.mono ?? false) : false;
      const textPlaceholder = control.kind === 'text' ? control.placeholder : undefined;
      return (
        <SettingsTextField
          id={id}
          label={field.label}
          {...(textMono ? { mono: true } : {})}
          {...(textPlaceholder !== undefined ? { placeholder: textPlaceholder } : {})}
          value={typeof value === 'string' ? value : ''}
          onChange={(next) => onChange(next)}
        />
      );
    }
  }
}

/**
 * One settings section — a `SettingsBlock` of model-driven `SettingsCard`s.
 *
 * Renders a `SettingsBlock` for the section, then a `SettingsCard` for each
 * group. Fields within each card are rendered as `Row`s. The `groupActions`
 * map lets callers inject actions into specific card headers — used by the
 * `paperless/endpoint` group for `TestConnectionAction`.
 *
 * Tier: features/ — knows the field model, composes primitives + SecretField.
 */
export function SettingsSection({
  section,
  values,
  reindexKeys,
  defaultKeys,
  onChange,
  groupActions,
}: SettingsSectionProps): React.ReactElement {
  return (
    <SettingsBlock
      id={section.id}
      title={section.title}
      subtitle={section.subtitle}
    >
      {section.groups.map((group) => (
        <SettingsCard
          key={group.id}
          title={group.title}
          {...(group.subtitle !== undefined ? { subtitle: group.subtitle } : {})}
          {...(groupActions?.[group.id] !== undefined ? { headerActions: groupActions[group.id] } : {})}
        >
          {group.fields.map((field, index) => {
            // A single-element control can be focused from its label; a Segmented
            // group or a SecretField (multiple elements) cannot.
            const labellable =
              field.control.kind !== 'segmented' && field.control.kind !== 'secret';
            const needsReindex = reindexKeys?.has(field.key) ?? false;
            const isDefault = defaultKeys?.has(field.key) ?? false;
            const hint = needsReindex ? (
              <>
                {field.hint}
                <span className={styles['reindex-note']!}>
                  Changing this requires re-indexing all documents.
                </span>
              </>
            ) : (
              field.hint
            );
            const controlId = labellable ? `setting-${field.key}` : undefined;
            return (
              <Row
                key={field.key}
                label={field.label}
                hint={hint}
                env={field.key}
                {...(controlId !== undefined ? { controlId } : {})}
                last={index === group.fields.length - 1}
                isDefault={isDefault}
              >
                <FieldControl
                  field={field}
                  value={values[field.key]}
                  onChange={(next) => onChange(field.key, next)}
                />
              </Row>
            );
          })}
        </SettingsCard>
      ))}
    </SettingsBlock>
  );
}
