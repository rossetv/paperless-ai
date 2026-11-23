import React from 'react';
import { SettingsLayout } from '../../../components/layout/SettingsLayout/SettingsLayout';
import { Spinner } from '../../../components/primitives/Spinner/Spinner';
import { EmptyState } from '../../../components/patterns/EmptyState/EmptyState';
import { useSettings, useUpdateSettings } from '../../../api/hooks';
import { errorDetail } from '../../../api/client';
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
 * A null `value` (key on its coded default) falls back to `default_value`, so the control shows
 * a real value rather than its empty state. Items with no field-model entry are skipped: the
 * model decides what is editable.
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

function reindexKeySet(items: SettingItem[]): Set<string> {
  return new Set(items.filter((i) => i.requires_reindex).map((i) => i.key));
}

function defaultKeySet(items: SettingItem[]): Set<string> {
  return new Set(items.filter((i) => i.source === 'default').map((i) => i.key));
}

/**
 * The screen once settings have loaded. Split out so `useUnsavedSettings` only ever mounts with
 * a real baseline, never a placeholder, which keeps dirty-tracking honest.
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
  // A re-index-forcing save (embedding model / chunking) shows a toast: the whole library is
  // being re-embedded server-side.
  const [reindexNotice, setReindexNotice] = React.useState(false);
  const [savedNotice, setSavedNotice] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  // SettingsLayout renders the h1 and takes no ref, so the heading is found within this screen.
  const screenRef = React.useRef<HTMLDivElement>(null);

  // Reload, closing the tab and leaving the site would drop the edits. In-app navigation is not
  // intercepted: BrowserRouter has no blocker.
  React.useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [isDirty]);

  const handleChange = (key: string, value: ConfigValue | null): void => {
    // `null` is an untouched secret: restore the baseline (the server mask) so the key counts as
    // unchanged. The baseline is undefined for a key the server never sent, hence the ''.
    const base = baseline[key];
    setValue(key, value === null ? (base ?? '') : value);
  };

  const handleSave = (): void => {
    if (!isDirty) return;
    const changes: Record<string, string> = {};
    for (const [key, value] of Object.entries(changedValues())) {
      changes[key] = serialiseValue(value);
    }
    setSaveError(null);
    save.mutate(
      { changes },
      {
        onSuccess: (data) => {
          if (data.reindex_triggered) {
            setReindexNotice(true);
            return;
          }
          setSavedNotice(true);
          // The save bar goes inert with the focused button inside it; park focus on the page
          // heading rather than let it fall to the body, without scrolling the person's place.
          const heading = screenRef.current?.querySelector('h1');
          heading?.setAttribute('tabindex', '-1');
          heading?.focus({ preventScroll: true });
        },
        onError: (error) => {
          setSaveError(errorDetail(error, 'Could not save the settings. Try again.'));
        },
      },
    );
  };

  return (
    <>
      <div ref={screenRef}>
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
      </div>
      <SaveBar
        dirtyCount={changedKeys.length}
        isPending={save.isPending}
        onDiscard={discard}
        onSave={handleSave}
        reindexPending={changedKeys.some((k) => reindexKeys.has(k))}
      />
      {saveError !== null && (
        <Toast
          message={saveError}
          variant="error"
          onDismiss={() => setSaveError(null)}
        />
      )}
      {savedNotice && (
        <Toast
          message="Settings saved."
          variant="info"
          onDismiss={() => setSavedNotice(false)}
          dismissAfterMs={4000}
        />
      )}
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
 * The Settings screen: every configuration value, editable in-app. Save sends only the changed
 * keys, each serialised back to a string.
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
