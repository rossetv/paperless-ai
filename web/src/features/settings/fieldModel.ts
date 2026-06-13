/**
 * Settings field model — re-export barrel.
 *
 * The 741-line monolith has been split into focused modules under fieldModel/:
 *   types.ts    — control, field, group, section interfaces + ConfigValue/SettingsDraft
 *   sections.ts — the SETTINGS_SECTIONS data array
 *   helpers.ts  — allFieldKeys, fieldByKey, parseValue, serialiseValue
 *
 * All existing imports (`from './fieldModel'`) continue to resolve here.
 * New code is encouraged to import directly from the sub-module it needs.
 *
 * Tier: features/ — this encodes domain knowledge of the config keys.
 */

export * from './fieldModel/types';
export * from './fieldModel/sections';
export * from './fieldModel/helpers';
