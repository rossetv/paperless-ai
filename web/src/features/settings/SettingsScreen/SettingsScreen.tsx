import React from 'react';
import { SettingsLayout } from '../../../components/layout/SettingsLayout/SettingsLayout';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
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
import { ConnectionsPanel } from '../ConnectionsPanel/ConnectionsPanel';
import { SaveBar } from '../SaveBar/SaveBar';
import { Toast } from '../../../components/patterns/Toast/Toast';

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
  // A re-index-forcing save (embedding model / chunking) surfaces a toast so
  // the operator knows their whole library is being re-embedded server-side.
  const [reindexNotice, setReindexNotice] = React.useState(false);

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
    save.mutate(
      { changes },
      {
        onSuccess: (data) => {
          // The server forces a full rebuild when a re-index key changed; let
          // the operator know their library is being re-embedded.
          if (data.reindex_triggered) setReindexNotice(true);
        },
      },
    );
  };

  return (
    <>
      <SettingsLayout
        title="Settings"
        subtitle="Configure your Paperless AI deployment. Saved changes apply immediately — daemons hot-load them with no restart."
      >
        {SETTINGS_SECTIONS.map((section) =>
          section.id === 'connections' ? (
            <ConnectionsPanel
              key={section.id}
              section={section}
              values={draft}
              onChange={handleChange}
              reindexKeys={reindexKeys}
              defaultKeys={defaultKeys}
            />
          ) : (
            <SettingsSection
              key={section.id}
              section={section}
              values={draft}
              reindexKeys={reindexKeys}
              defaultKeys={defaultKeys}
              onChange={handleChange}
            />
          ),
        )}
      </SettingsLayout>
      <SaveBar
        dirtyCount={changedKeys.length}
        isPending={save.isPending}
        onDiscard={discard}
        onSave={handleSave}
      />
      {reindexNotice && (
        <Toast
          message="Settings saved. Re-indexing all documents — re-embedding your library, which may take a few minutes."
          variant="info"
          onDismiss={() => setReindexNotice(false)}
          dismissAfterMs={8000}
        />
      )}
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
        <Spinner size="large" label="Loading settings…" />
      </SettingsLayout>
    );
  }

  if (query.isError || query.data === undefined) {
    return (
      <SettingsLayout title="Settings">
        <div role="alert">
          <EmptyState
            icon="warning"
            message="Could not load settings."
            description="Refresh the page to try again."
          />
        </div>
      </SettingsLayout>
    );
  }

  return <SettingsContent items={query.data.settings} />;
}
