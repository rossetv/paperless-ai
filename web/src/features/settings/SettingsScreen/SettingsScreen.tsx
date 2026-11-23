import React from 'react';
import { useBlocker, useLocation } from 'react-router-dom';
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
import { readStickyOffset } from '../../../components/layout/SettingsSideNav/SettingsSideNav';
import { LeaveSettingsModal } from '../LeaveSettingsModal/LeaveSettingsModal';
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
  const screenRef = React.useRef<HTMLDivElement>(null);
  const barRef = React.useRef<HTMLDivElement>(null);
  // The last settings control the person focused, where focus returns after a save.
  const lastFieldRef = React.useRef<HTMLElement | null>(null);
  // The last input the person used. Focusing a text field after a tap raises the on-screen
  // keyboard, so only a keyboard save returns focus to a field.
  const keyboardRef = React.useRef(false);

  React.useEffect(() => {
    const onKey = (): void => {
      keyboardRef.current = true;
    };
    const onPointer = (): void => {
      keyboardRef.current = false;
    };
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('pointerdown', onPointer, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
      document.removeEventListener('pointerdown', onPointer, true);
    };
  }, []);

  React.useEffect(() => {
    const screen = screenRef.current;
    if (screen === null) return undefined;
    const remember = (event: FocusEvent): void => {
      const target = event.target;
      if (target instanceof HTMLElement && target.matches('input, select, textarea, button')) {
        lastFieldRef.current = target;
      }
    };
    screen.addEventListener('focusin', remember);
    return () => screen.removeEventListener('focusin', remember);
  }, []);

  // After a save the focused Save button goes inert with the bar. Leave focus alone if the person
  // has moved on to a field; otherwise, after a keyboard save, return it to the last field, or the heading as a last resort.
  const restoreFocus = (fromKeyboard: boolean): void => {
    const active = document.activeElement;
    if (active !== null && active !== document.body && !barRef.current?.contains(active)) return;
    const field = lastFieldRef.current;
    if (fromKeyboard && field?.isConnected === true && !field.hasAttribute('disabled') && !field.closest('[inert]')) {
      field.focus({ preventScroll: true });
      return;
    }
    // SettingsLayout takes no ref, so the heading is found within this screen.
    const heading = screenRef.current?.querySelector('h1');
    heading?.setAttribute('tabindex', '-1');
    heading?.focus({ preventScroll: true });
  };

  // Reload, closing the tab and leaving the site would drop the edits; in-app navigation is
  // caught by the blocker below.
  React.useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [isDirty]);

  // A hash or search change within /settings moves between sections and never asks.
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty &&
      currentLocation.pathname !== nextLocation.pathname &&
      // Sign-out and a lapsed session end here; they must never wait on a prompt.
      nextLocation.pathname !== '/login',
  );

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
    const fromKeyboard = keyboardRef.current;
    setSaveError(null);
    setSavedNotice(false);
    setReindexNotice(false);
    save.mutate(
      { changes },
      {
        onSuccess: (data) => {
          if (data.reindex_triggered) {
            setReindexNotice(true);
          } else {
            setSavedNotice(true);
          }
          restoreFocus(fromKeyboard);
        },
        onError: (error) => {
          setSaveError(errorDetail(error, 'Could not save the settings. Try again.'));
        },
      },
    );
  };

  // The sections only exist once the data has loaded, so the browser's own jump to the
  // landing hash finds nothing; do it once they have rendered.
  const landingHash = useLocation().hash.slice(1);
  React.useEffect(() => {
    const el = landingHash === '' ? null : document.getElementById(landingHash);
    if (el === null) return;
    window.scrollTo({
      top: el.getBoundingClientRect().top + window.scrollY - readStickyOffset(),
      behavior: 'instant',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      <div ref={barRef} style={{ display: 'contents' }}>
        <SaveBar
          dirtyCount={changedKeys.length}
          isPending={save.isPending}
          onDiscard={discard}
          onSave={handleSave}
          reindexPending={changedKeys.some((k) => reindexKeys.has(k))}
        />
      </div>
      {blocker.state === 'blocked' && (
        <LeaveSettingsModal onStay={() => blocker.reset()} onLeave={() => blocker.proceed()} />
      )}
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

  if (query.data === undefined) {
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
