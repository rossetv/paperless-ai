/**
 * Draft-state hook for the Settings screen.
 *
 * Holds an editable draft of the configuration over a saved baseline. The
 * screen edits the draft freely via `setValue`; the hook derives which keys
 * differ from the baseline so the screen can show an unsaved-changes count
 * and send only the changed keys on save.
 *
 * `discard` reverts the draft to the baseline. When the baseline prop itself
 * changes — the server returns fresh state after a successful save — the
 * draft re-bases onto it, so a save naturally clears the dirty state.
 *
 * Pure state — no network. Tier: features/ (settings-specific).
 */

import { useEffect, useRef, useState } from 'react';
import type { ConfigValue, SettingsDraft } from './fieldModel';

/** Structural equality for two config values, handling the array (list) case. */
function valuesEqual(a: ConfigValue, b: ConfigValue): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => item === b[i]);
  }
  return a === b;
}

/** The shape returned by {@link useUnsavedSettings}. */
export interface UnsavedSettings {
  /** The current editable draft — baseline plus any in-flight edits. */
  draft: SettingsDraft;
  /** Set one config key in the draft. */
  setValue: (key: string, value: ConfigValue) => void;
  /** The keys whose draft value differs from the baseline. */
  changedKeys: string[];
  /** True when at least one key has changed. */
  isDirty: boolean;
  /** A fresh object holding only the changed keys — the typed changed values. */
  changedValues: () => SettingsDraft;
  /** Revert the draft to the baseline, discarding all edits. */
  discard: () => void;
}

/**
 * Track unsaved edits to the configuration against a saved baseline.
 *
 * Operates on the *parsed* draft (`SettingsDraft` — typed values), not the
 * wire shape. The Settings screen parses the server's `SettingItem[]` into a
 * `SettingsDraft` baseline and serialises `changedValues()` back to a string
 * `changes` map before posting.
 *
 * @param baseline The last-saved settings as a parsed draft.
 */
export function useUnsavedSettings(baseline: SettingsDraft): UnsavedSettings {
  const [draft, setDraft] = useState<SettingsDraft>(baseline);

  // Re-base the draft whenever the baseline reference changes — i.e. after a
  // save returns fresh server state, or the initial fetch resolves.
  const lastBaseline = useRef(baseline);
  useEffect(() => {
    if (lastBaseline.current !== baseline) {
      lastBaseline.current = baseline;
      setDraft(baseline);
    }
  }, [baseline]);

  const setValue = (key: string, value: ConfigValue): void => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const changedKeys = Object.keys(draft).filter((key) => {
    const draftVal = draft[key];
    const baseVal = baseline[key];
    // A key present in the draft but absent from the baseline is always changed.
    if (draftVal === undefined || baseVal === undefined) return draftVal !== baseVal;
    return !valuesEqual(draftVal, baseVal);
  });

  const changedValues = (): SettingsDraft => {
    const out: SettingsDraft = {};
    for (const key of changedKeys) {
      const val = draft[key];
      if (val !== undefined) {
        out[key] = val;
      }
    }
    return out;
  };

  const discard = (): void => {
    setDraft(baseline);
  };

  return {
    draft,
    setValue,
    changedKeys,
    isDirty: changedKeys.length > 0,
    changedValues,
    discard,
  };
}
