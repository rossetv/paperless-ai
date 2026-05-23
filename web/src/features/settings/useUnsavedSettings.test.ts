import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUnsavedSettings } from './useUnsavedSettings';
import type { SettingsDraft } from './fieldModel';

const BASELINE: SettingsDraft = {
  PAPERLESS_URL: 'http://x',
  SEARCH_TOP_K: 10,
  OCR_INCLUDE_PAGE_MODELS: false,
  AI_MODELS: ['a', 'b'],
};

describe('useUnsavedSettings', () => {
  it('starts with the baseline as the draft and no changes', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    expect(result.current.draft).toEqual(BASELINE);
    expect(result.current.changedKeys).toEqual([]);
    expect(result.current.isDirty).toBe(false);
  });

  it('records a single changed key after an edit', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    expect(result.current.draft['SEARCH_TOP_K']).toBe(25);
    expect(result.current.changedKeys).toEqual(['SEARCH_TOP_K']);
    expect(result.current.isDirty).toBe(true);
  });

  it('drops a key from changedKeys when it is edited back to the baseline value', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    act(() => result.current.setValue('SEARCH_TOP_K', 10));
    expect(result.current.changedKeys).toEqual([]);
    expect(result.current.isDirty).toBe(false);
  });

  it('compares array values structurally, not by reference', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('AI_MODELS', ['a', 'b']));
    // Same contents → not a change.
    expect(result.current.changedKeys).toEqual([]);
    act(() => result.current.setValue('AI_MODELS', ['a', 'b', 'c']));
    expect(result.current.changedKeys).toEqual(['AI_MODELS']);
  });

  it('changedValues holds only the changed keys', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    act(() => result.current.setValue('PAPERLESS_URL', 'http://y'));
    expect(result.current.changedValues()).toEqual({
      SEARCH_TOP_K: 25,
      PAPERLESS_URL: 'http://y',
    });
  });

  it('discard() reverts the draft to the baseline', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    act(() => result.current.discard());
    expect(result.current.draft).toEqual(BASELINE);
    expect(result.current.changedKeys).toEqual([]);
  });

  it('adopts a new baseline when the baseline reference changes (after a save)', () => {
    const { result, rerender } = renderHook(
      ({ base }: { base: SettingsDraft }) => useUnsavedSettings(base),
      { initialProps: { base: BASELINE } },
    );
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    const saved: SettingsDraft = { ...BASELINE, SEARCH_TOP_K: 25 };
    rerender({ base: saved });
    // The new server state becomes the baseline; the draft is clean again.
    expect(result.current.draft).toEqual(saved);
    expect(result.current.isDirty).toBe(false);
  });

  it('counts multiple distinct changed keys', () => {
    const { result } = renderHook(() => useUnsavedSettings(BASELINE));
    act(() => result.current.setValue('SEARCH_TOP_K', 25));
    act(() => result.current.setValue('OCR_INCLUDE_PAGE_MODELS', true));
    expect(result.current.changedKeys).toHaveLength(2);
  });
});
