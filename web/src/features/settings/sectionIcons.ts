/**
 * Icon assignments for every settings navigation item.
 *
 * Maps each settings section id (and the access-control items) to the icon
 * name used in the side-nav rail. Defined here once so both the rail
 * (`SettingsSideNav`) and any future consumer can import without coupling.
 *
 * The nine section ids match `SETTINGS_SECTIONS` in `fieldModel.ts`. The
 * `users` and `keys` ids cover the Access Control group.
 *
 * Tier: features/settings — shared domain knowledge for the settings area.
 */

import type { IconName } from '../../components/primitives/Icon/Icon';

export const SETTINGS_SECTION_ICONS: Record<string, IconName> = {
  paperless: 'link',
  llm: 'sparkle',
  search: 'search',
  embed: 'waves',
  ocr: 'eye',
  classify: 'paragraph',
  tags: 'tag',
  perf: 'lightning',
  logs: 'list-lines',
  users: 'users',
  keys: 'key',
};
