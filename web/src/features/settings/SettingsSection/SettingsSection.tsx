import React from 'react';
import { SettingsBlock } from '../../../components/primitives/SettingsBlock/SettingsBlock';
import { SettingsCard } from '../../../components/primitives/SettingsCard/SettingsCard';
import { Row } from '../../../components/primitives/Row/Row';
import { Disclosure } from '../../../components/primitives/Disclosure/Disclosure';
import { FieldControl } from '../FieldControl/FieldControl';
import type {
  ConfigValue,
  SettingsDraft,
  SettingsSection as SectionModel,
  SettingsField,
} from '../fieldModel';

export interface SettingsSectionProps {
  /** The section descriptor from the field model. */
  section: SectionModel;
  /** The current draft values, keyed by config-key name. */
  values: SettingsDraft;
  /**
   * The config keys whose change requires a full document re-index — the
   * server's `requires_reindex` set. A field in this set shows an amber
   * "Rebuilds the index on save" pill beside its label.
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
 * Render one field as a `Row` with the correct `FieldControl` inside.
 *
 * Handles the `controlId` labellability rule (segmented and secret are not
 * labellable), the `requiresReindex` pill, the `isDefault` badge, and the
 * `reasoningValue` pass-through for composite select+reasoning controls.
 */
function FieldRow({
  field,
  values,
  reindexKeys,
  defaultKeys,
  onChange,
  last,
}: {
  field: SettingsField;
  values: SettingsDraft;
  reindexKeys?: ReadonlySet<string>;
  defaultKeys?: ReadonlySet<string>;
  onChange: (key: string, value: ConfigValue | null) => void;
  last: boolean;
}): React.ReactElement {
  // A single-element control can be focused from its label; a Segmented
  // group or a SecretField (multiple elements) cannot.
  const labellable =
    field.control.kind !== 'segmented' && field.control.kind !== 'secret';
  const controlId = labellable ? `setting-${field.key}` : undefined;
  const requiresReindex = reindexKeys?.has(field.key) ?? false;
  const isDefault = defaultKeys?.has(field.key) ?? false;

  // For select controls with a reasoningKey, pass the reasoning draft value
  // through so FieldControl can bind the companion segmented.
  const reasoningValue =
    field.control.kind === 'select' && field.control.reasoningKey !== undefined
      ? values[field.control.reasoningKey]
      : undefined;

  return (
    <Row
      label={field.label}
      hint={field.hint}
      env={field.key}
      {...(controlId !== undefined ? { controlId } : {})}
      last={last}
      isDefault={isDefault}
      requiresReindex={requiresReindex}
    >
      <FieldControl
        field={field}
        value={values[field.key]}
        onChange={onChange}
        {...(controlId !== undefined ? { controlId } : {})}
        {...(reasoningValue !== undefined ? { reasoningValue } : {})}
      />
    </Row>
  );
}

/**
 * One settings section — a `SettingsBlock` of model-driven `SettingsCard`s.
 *
 * Renders a `SettingsBlock` for the section, then a `SettingsCard` for each
 * group. Fields within each card are rendered as `Row`s. When a group has an
 * `advanced` array, those fields appear inside a collapsed `Disclosure` with
 * an "Advanced · {n}" summary, below the primary fields.
 *
 * The `groupActions` map lets callers inject actions into specific card headers
 * — used by the `paperless/endpoint` group for `TestConnectionAction`.
 *
 * Tier: features/ — knows the field model, composes primitives + FieldControl.
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
      {section.groups.map((group) => {
        const advancedFields = group.advanced ?? [];
        const hasAdvanced = advancedFields.length > 0;
        // The "last" row logic must account for both primary and advanced fields.
        // If there are advanced fields, the last primary row is never truly last
        // in the visual card — the disclosure follows — so we keep the divider.
        const primaryFields = group.fields;

        return (
          <SettingsCard
            key={group.id}
            title={group.title}
            {...(group.subtitle !== undefined ? { subtitle: group.subtitle } : {})}
            {...(groupActions?.[group.id] !== undefined ? { headerActions: groupActions[group.id] } : {})}
          >
            {primaryFields.map((field, index) => (
              <FieldRow
                key={field.key}
                field={field}
                values={values}
                {...(reindexKeys !== undefined ? { reindexKeys } : {})}
                {...(defaultKeys !== undefined ? { defaultKeys } : {})}
                onChange={onChange}
                last={index === primaryFields.length - 1 && !hasAdvanced}
              />
            ))}
            {hasAdvanced && (
              <Disclosure summary={`Advanced · ${advancedFields.length}`}>
                {advancedFields.map((field, index) => (
                  <FieldRow
                    key={field.key}
                    field={field}
                    values={values}
                    {...(reindexKeys !== undefined ? { reindexKeys } : {})}
                    {...(defaultKeys !== undefined ? { defaultKeys } : {})}
                    onChange={onChange}
                    last={index === advancedFields.length - 1}
                  />
                ))}
              </Disclosure>
            )}
          </SettingsCard>
        );
      })}
    </SettingsBlock>
  );
}
