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
  draft: SettingsDraft;
  setValue: (key: string, value: ConfigValue) => void;
  changedKeys: string[];
  isDirty: boolean;
  /** A fresh object holding only the changed keys. */
  changedValues: () => SettingsDraft;
  discard: () => void;
}

/**
 * Track unsaved edits to the parsed (typed) configuration against a saved baseline.
 *
 * When the baseline reference changes (e.g. fresh server state after a save) the draft re-bases
 * onto it, so a successful save clears the dirty state.
 */
export function useUnsavedSettings(baseline: SettingsDraft): UnsavedSettings {
  const [draft, setDraft] = useState<SettingsDraft>(baseline);

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
