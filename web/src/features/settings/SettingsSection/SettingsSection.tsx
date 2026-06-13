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
 * Resolve a field's control to a concrete one for the current draft.
 *
 * A `conditional` control renders a different concrete control depending on the
 * live value of another field (its `on` key) — e.g. the embedding model is a
 * dropdown when `EMBEDDING_PROVIDER` is `openai` and a free-text field when it
 * is `ollama`. Every other control kind is already concrete and returned as-is.
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
 * Locks the "Ollama" provider choice until `OLLAMA_BASE_URL` is configured under
 * Connections — a step may not select a provider whose connection is missing
 * (the Settings API enforces the same rule on save). Returns the control
 * unchanged when nothing is locked, so referential identity is preserved.
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
 * Whether a field's row should render for the current draft. A field with a
 * `visibleWhen` condition (e.g. a reasoning-effort row) shows only when the
 * referenced key matches — hiding `reasoning_effort` when the step is on Ollama.
 */
function isFieldVisible(field: SettingsField, values: SettingsDraft): boolean {
  if (field.visibleWhen === undefined) return true;
  return values[field.visibleWhen.key] === field.visibleWhen.equals;
}

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
   * actions slot. Available for any group that needs injected header actions.
   */
  groupActions?: Record<string, React.ReactNode>;
}

/**
 * Render one field as a `Row` with the correct `FieldControl` inside.
 *
 * Handles the `controlId` labellability rule (segmented and secret are not
 * labellable), the `requiresReindex` pill, the `isDefault` badge, and the
 * `reasoningValue` pass-through for composite select+reasoning controls.
 *
 * Exported so other settings panels (e.g. `ConnectionsPanel`) render rows
 * through the identical Row + FieldControl wiring — keeping label association,
 * the shared control-column width and compact-control centring consistent
 * rather than re-implementing it per panel.
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
  // Resolve a conditional control (e.g. the embedding model) to the concrete
  // control that applies to the current draft, then lock any provider option
  // whose connection is not configured (Ollama before OLLAMA_BASE_URL is set).
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

  // For select controls with a reasoningKey, pass the reasoning draft value
  // through so FieldControl can bind the companion segmented.
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
 * One settings section — a `SettingsBlock` of model-driven `SettingsCard`s.
 *
 * Renders a `SettingsBlock` for the section, then a `SettingsCard` for each
 * group. Fields within each card are rendered as `Row`s. When a group has an
 * `advanced` array, those fields appear inside a collapsed `Disclosure` with
 * an "Advanced · {n}" summary, below the primary fields.
 *
 * The `groupActions` map lets callers inject actions into specific card headers.
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
        // Drop rows hidden for the current draft (e.g. a reasoning-effort row
        // whose step is on Ollama) before the "last row" divider maths, so the
        // divider lands on the last *visible* row.
        const advancedFields = (group.advanced ?? []).filter((field) =>
          isFieldVisible(field, values),
        );
        const hasAdvanced = advancedFields.length > 0;
        // The "last" row logic must account for both primary and advanced fields.
        // If there are advanced fields, the last primary row is never truly last
        // in the visual card — the disclosure follows — so we keep the divider.
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
