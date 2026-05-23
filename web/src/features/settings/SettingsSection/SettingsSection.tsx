import React from 'react';
import { SectionCard } from '../../../components/primitives/SectionCard/SectionCard';
import { Icon } from '../../../components/primitives/Icon/Icon';
import type { IconName } from '../../../components/primitives/Icon/Icon';
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
// No fieldModel runtime imports needed — SettingsListField owns its own parsing.
import styles from './SettingsSection.module.css';

/**
 * Maps every section id to the icon shown in its SectionCard header tile.
 * Exported so the side-nav or any future caller can reuse the same mapping.
 */
export const SETTINGS_SECTION_ICONS: Record<string, IconName> = {
  paperless: 'link',
  llm: 'sparkle',
  search: 'search',
  embed: 'waves',
  ocr: 'eye',
  classify: 'paragraph',
  tags: 'tag',
  perf: 'lightning',
  logs: 'list-lines',
};

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
   * this set shows a subtle "default" badge so the operator can tell a
   * coded default from an explicit override.
   */
  defaultKeys?: ReadonlySet<string>;
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
 * A `list` control renders a pill-list UI via `SettingsListField`; the draft
 * holds a `string[]` and the component owns its own add/remove/reorder logic.
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
  defaultKeys,
  onChange,
  children,
}: SettingsSectionProps): React.ReactElement {
  const iconName = SETTINGS_SECTION_ICONS[section.id];
  const iconNode =
    iconName !== undefined ? <Icon name={iconName} size="large" /> : undefined;

  return (
    <SectionCard
      id={section.id}
      title={section.title}
      subtitle={section.subtitle}
      icon={iconNode}
    >
      {section.fields.map((field, index) => {
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
              {' '}
              Changing this requires re-indexing all documents — run a full
              rebuild from the Index page.
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
            last={index === section.fields.length - 1 && children === undefined}
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
      {children}
    </SectionCard>
  );
}
