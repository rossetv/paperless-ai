import React from 'react';
import { SettingsBlock } from '../../../components/primitives/SettingsBlock/SettingsBlock';
import { SettingsCard } from '../../../components/primitives/SettingsCard/SettingsCard';
import { Row } from '../../../components/primitives/Row/Row';
import { Disclosure } from '../../../components/primitives/Disclosure/Disclosure';
import { FieldControl } from '../FieldControl/FieldControl';
import type {
  ConcreteControl,
  ConfigValue,
  SettingsDraft,
  SettingsSection as SectionModel,
  SettingsField,
} from '../fieldModel';

/**
 * Resolve a `conditional` control to the concrete one selected by its `on` key's live value
 * (e.g. the embedding model is a dropdown for `openai`, free text for `ollama`).
 */
function resolveControl(
  control: SettingsField['control'],
  values: SettingsDraft,
): ConcreteControl {
  if (control.kind !== 'conditional') return control;
  const selector = values[control.on];
  const variant =
    typeof selector === 'string' ? control.variants[selector] : undefined;
  return variant ?? control.fallback;
}

/**
 * Grey out any segmented option whose `disabledWhenEmpty` key has no value.
 *
 * A step may not pick a provider whose connection is missing (the Settings API enforces the
 * same rule on save). Returns the same object when nothing is locked, preserving identity.
 */
function applySegmentedLocks(
  control: ConcreteControl,
  values: SettingsDraft,
): ConcreteControl {
  if (control.kind !== 'segmented') return control;
  let changed = false;
  const options = control.options.map((option) => {
    if (
      option.disabledWhenEmpty !== undefined &&
      String(values[option.disabledWhenEmpty] ?? '').trim() === ''
    ) {
      changed = true;
      return {
        ...option,
        disabled: true,
        title: 'Configure Ollama under Connections to enable',
      };
    }
    return option;
  });
  return changed ? { ...control, options } : control;
}

/**
 * A field with `visibleWhen` shows only when the referenced key matches (e.g. no reasoning effort
 * on Ollama).
 */
function isFieldVisible(field: SettingsField, values: SettingsDraft): boolean {
  if (field.visibleWhen === undefined) return true;
  return values[field.visibleWhen.key] === field.visibleWhen.equals;
}

export interface SettingsSectionProps {
  section: SectionModel;
  values: SettingsDraft;
  /** The server's `requires_reindex` keys; each gets an amber "Rebuilds the index on save" pill. */
  reindexKeys?: ReadonlySet<string>;
  /** Keys on their coded default; each gets a "default" badge to tell it from an override. */
  defaultKeys?: ReadonlySet<string>;
  /** For a secret key the value is the new secret, or `null` when the user is not replacing it. */
  onChange: (key: string, value: ConfigValue | null) => void;
  /** Group id to a node rendered in that group's card-header actions slot. */
  groupActions?: Record<string, React.ReactNode>;
}

/**
 * Render one field as a `Row` with the matching `FieldControl` inside.
 *
 * Exported so other settings panels (e.g. `ConnectionsPanel`) share the same label association
 * and control-column layout.
 */
export function FieldRow({
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
  const control = applySegmentedLocks(
    resolveControl(field.control, values),
    values,
  );
  const resolvedField =
    control === field.control ? field : { ...field, control };

  // A single-element control can be focused from its label; a Segmented
  // group or a SecretField (multiple elements) cannot.
  const labellable = control.kind !== 'segmented' && control.kind !== 'secret';
  const controlId = labellable ? `setting-${field.key}` : undefined;
  const requiresReindex = reindexKeys?.has(field.key) ?? false;
  const isDefault = defaultKeys?.has(field.key) ?? false;

  const reasoningValue =
    control.kind === 'select' && control.reasoningKey !== undefined
      ? values[control.reasoningKey]
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
        field={resolvedField}
        value={values[field.key]}
        onChange={onChange}
        {...(controlId !== undefined ? { controlId } : {})}
        {...(reasoningValue !== undefined ? { reasoningValue } : {})}
      />
    </Row>
  );
}

/**
 * One settings section: a `SettingsBlock` with a `SettingsCard` per group. A group's `advanced`
 * fields go in a collapsed "Advanced · {n}" `Disclosure` below the primary fields.
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
        // Filter hidden rows before the "last row" divider maths so the divider lands on the last
        // visible row.
        const advancedFields = (group.advanced ?? []).filter((field) =>
          isFieldVisible(field, values),
        );
        const hasAdvanced = advancedFields.length > 0;
        // When advanced fields follow, the last primary row keeps its divider: the disclosure is
        // below it.
        const primaryFields = group.fields.filter((field) =>
          isFieldVisible(field, values),
        );

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
