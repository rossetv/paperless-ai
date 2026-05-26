import React from 'react';
import { SettingsLayout } from '../../../components/layout/SettingsLayout/SettingsLayout';
import { useSettings, useUpdateSettings } from '../../../api/hooks';
import type { SettingItem } from '../../../api/types';
import type { ConfigValue, SettingsDraft } from '../fieldModel';
import {
  SETTINGS_SECTIONS,
  fieldByKey,
  parseValue,
  serialiseValue,
} from '../fieldModel';
import { useUnsavedSettings } from '../useUnsavedSettings';
import { SettingsSection } from '../SettingsSection/SettingsSection';
import { TestConnectionAction } from '../TestConnectionAction/TestConnectionAction';
import { SaveBar } from '../SaveBar/SaveBar';
import styles from './SettingsScreen.module.css';

/**
 * Parse the server's `SettingItem[]` into the typed draft the screen edits.
 *
 * Each item's string `value` is parsed per its field's control kind
 * (`parseValue`). When `value` is null (key on its coded default) and a
 * `default_value` is present, the coded default is used as the raw string so
 * the control shows a meaningful value rather than its empty state. An item
 * with no matching field model entry is skipped — the model is the source of
 * truth for what is editable.
 */
function toDraft(items: SettingItem[]): SettingsDraft {
  const draft: SettingsDraft = {};
  for (const item of items) {
    const field = fieldByKey(item.key);
    if (field) {
      const raw = item.value ?? item.default_value ?? null;
      draft[item.key] = parseValue(field, raw);
    }
  }
  return draft;
}

/** The set of keys the server flags as needing a re-index when changed. */
function reindexKeySet(items: SettingItem[]): Set<string> {
  return new Set(items.filter((i) => i.requires_reindex).map((i) => i.key));
}

/** The set of keys whose value is currently on the coded default (source=default). */
function defaultKeySet(items: SettingItem[]): Set<string> {
  return new Set(items.filter((i) => i.source === 'default').map((i) => i.key));
}

/**
 * The inner screen, rendered once the settings have loaded.
 *
 * Split out so the draft hook (`useUnsavedSettings`) is only mounted with a
 * real baseline — never with a placeholder — which keeps the dirty-tracking
 * honest. `items` is the server's `SettingItem[]`; the baseline draft and the
 * re-index key set are derived from it.
 */
function SettingsContent({
  items,
}: {
  items: SettingItem[];
}): React.ReactElement {
  const baseline = React.useMemo(() => toDraft(items), [items]);
  const reindexKeys = React.useMemo(() => reindexKeySet(items), [items]);
  const defaultKeys = React.useMemo(() => defaultKeySet(items), [items]);
  const { draft, setValue, changedKeys, isDirty, changedValues, discard } =
    useUnsavedSettings(baseline);
  const save = useUpdateSettings();

  /**
   * Apply a field change. A secret field reports `null` when the user is NOT
   * replacing the key — in that case the draft must hold the baseline value
   * (the server mask) so the key counts as unchanged; any string is the new
   * secret.
   */
  const handleChange = (key: string, value: ConfigValue | null): void => {
    setValue(key, value === null ? (baseline[key] as ConfigValue) : value);
  };

  const handleSave = (): void => {
    if (!isDirty) return;
    const changes: Record<string, string> = {};
    for (const [key, value] of Object.entries(changedValues())) {
      changes[key] = serialiseValue(value);
    }
    save.mutate({ changes });
  };

  // The masked-token flag: the token is still the server mask while the draft
  // value equals the baseline value.
  const tokenIsMasked = draft['PAPERLESS_TOKEN'] === baseline['PAPERLESS_TOKEN'];

  // The group-actions map wires the TestConnectionAction into the Paperless
  // Endpoint card's headerActions slot.
  const paperlessGroupActions: Record<string, React.ReactNode> = {
    endpoint: (
      <TestConnectionAction
        url={typeof draft['PAPERLESS_URL'] === 'string' ? draft['PAPERLESS_URL'] : ''}
        token={typeof draft['PAPERLESS_TOKEN'] === 'string' ? draft['PAPERLESS_TOKEN'] : ''}
        tokenIsMasked={tokenIsMasked}
      />
    ),
  };

  return (
    <>
      <SettingsLayout
        title="Settings"
        subtitle="Configure your Paperless AI deployment. Saved changes apply immediately — daemons hot-load them with no restart."
      >
        {SETTINGS_SECTIONS.map((section) => (
          <SettingsSection
            key={section.id}
            section={section}
            values={draft}
            reindexKeys={reindexKeys}
            defaultKeys={defaultKeys}
            onChange={handleChange}
            {...(section.id === 'paperless' ? { groupActions: paperlessGroupActions } : {})}
          />
        ))}
      </SettingsLayout>
      <SaveBar
        dirtyCount={changedKeys.length}
        isPending={save.isPending}
        onDiscard={discard}
        onSave={handleSave}
      />
    </>
  );
}

/**
 * The Settings screen — every configuration value, editable in-app.
 *
 * Fetches the configuration, then renders the nine config sections inside
 * the shared `SettingsLayout`. The server's `SettingItem[]` is parsed into a
 * typed draft; unsaved edits are tracked against it, the sticky `SaveBar`
 * slides up when dirty, and Save sends only the changed keys each serialised
 * back to a string.
 *
 * Tier: features/ — composes layout + primitives + settings sub-features and
 * wires the settings hooks.
 */
export function SettingsScreen(): React.ReactElement {
  const query = useSettings();

  if (query.isPending) {
    return (
      <SettingsLayout title="Settings">
        <div className={styles['placeholder']}>Loading settings…</div>
      </SettingsLayout>
    );
  }

  if (query.isError || query.data === undefined) {
    return (
      <SettingsLayout title="Settings">
        <div className={`${styles['placeholder']} ${styles['placeholder-error']}`}>
          Could not load settings. Refresh to try again.
        </div>
      </SettingsLayout>
    );
  }

  return <SettingsContent items={query.data.settings} />;
}
